from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import secrets
import sys
import logging
import sqlite3
import time as _time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

from stock_engine import StockEngine
from ai_analyzer import AIAnalyzer
import auto_trader
import json
import yfinance as yf
import plotly
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from translations import get_translations

app = Flask(__name__)
# Use persistent secret key from .env (prevents session loss on restart)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))

# Session security configurations
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rate Limiting
_rate_limits = {}
_RATE_LIMIT_MAX = 20  # max requests per minute
_RATE_LIMIT_WINDOW = 60  # seconds

# Smart Market Data Cache (5-minute TTL)
_market_cache = {}
_CACHE_TTL = 300  # 5 minutes

def get_cached_market_data(symbol, period="2d"):
    """Fetches market data with caching to avoid redundant API calls."""
    cache_key = f"{symbol}_{period}"
    now = _time.time()
    if cache_key in _market_cache:
        data, timestamp = _market_cache[cache_key]
        if now - timestamp < _CACHE_TTL:
            return data
    try:
        t = yf.Ticker(symbol)
        data = t.history(period=period)
        if data is not None and not data.empty:
            _market_cache[cache_key] = (data, now)
            return data
    except:
        pass
    return _market_cache.get(cache_key, (None, 0))[0]

def check_rate_limit(username):
    now = _time.time()
    if username not in _rate_limits:
        _rate_limits[username] = []
    _rate_limits[username] = [t for t in _rate_limits[username] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limits[username]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limits[username].append(now)
    return True

# SQLite Portfolio
PORTFOLIO_DB = 'portfolio.db'

def init_portfolio_db():
    conn = sqlite3.connect(PORTFOLIO_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        username TEXT,
        ticker TEXT,
        entry_price REAL,
        sl REAL,
        tp REAL,
        shares INTEGER,
        date TEXT,
        status TEXT DEFAULT 'open',
        close_price REAL,
        pnl REAL DEFAULT 0
    )''')
    conn.commit()
    conn.close()

init_portfolio_db()

@app.context_processor
def inject_translations():
    lang = session.get('lang', 'ar')
    return dict(t=get_translations(lang), lang=lang)

@app.route('/set_lang/<lang>')
def set_lang(lang):
    if lang in ['ar', 'en']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.plot.ly https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    response.headers['Content-Security-Policy'] = csp
    return response

# Hardcoded credentials for demonstration
# In production, use a database or environment variables
import os
DEFAULT_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Database utility functions
def load_users():
    try:
        with open('users.json', 'r', encoding='utf-8') as f:
            users = json.load(f)
            
        # Migration: Convert string device_id to list device_ids
        modified = False
        for uname, data in users.items():
            if 'device_id' in data:
                old_id = data.pop('device_id')
                data['device_ids'] = [old_id] if old_id else []
                data['max_devices'] = data.get('max_devices', 1)
                modified = True
            elif 'device_ids' not in data:
                data['device_ids'] = []
                data['max_devices'] = data.get('max_devices', 1)
                modified = True
        
        if modified:
            with open('users.json', 'w', encoding='utf-8') as f:
                json.dump(users, f, indent=2)
                
        return users
    except:
        # Default admin with hashed password "Az@123"
        hashed_pass = generate_password_hash("Az@123")
        return {"admin": {"password": hashed_pass, "start_date": "2024-01-01", "end_date": "2099-12-31", "role": "admin", "device_ids": [], "max_devices": 1}}

def save_users(users):
    with open('users.json', 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)

def load_approvals():
    try:
        with open('approvals.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_approvals(approvals):
    with open('approvals.json', 'w', encoding='utf-8') as f:
        json.dump(approvals, f, indent=2)

def log_activity(username, action, extra_data=None):
    try:
        with open('activity_log.json', 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except:
        logs = []
    
    logs.append({
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "user": username,
        "action": action,
        "extra_data": extra_data
    })
    
    # Keep only last 100 logs
    logs = logs[-100:]
    
    with open('activity_log.json', 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2)

def load_announcements():
    try:
        with open('announcements.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_announcements(ann):
    with open('announcements.json', 'w', encoding='utf-8') as f:
        json.dump(ann, f, indent=2)

def load_tickets():
    try:
        with open('tickets.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_tickets(tickets):
    with open('tickets.json', 'w', encoding='utf-8') as f:
        json.dump(tickets, f, indent=2)

def load_logs():
    try:
        with open('activity_log.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    lang = session.get('lang', 'ar')
    t = get_translations(lang)
    error = None
    import time
    if request.method == 'POST':
        if 'lockout_until' in session:
            if time.time() < session['lockout_until']:
                error = t['lockout_msg']
                return render_template('login.html', error=error)
            else:
                session.pop('lockout_until', None)
                session['login_attempts'] = 0

        username = request.form['username']
        password = request.form['password']
        device_id = request.form.get('device_id')
        users = load_users()
        
        if username in users:
            user_data = users[username]
            if check_password_hash(user_data['password'], password):
                # Device Locking Logic
                if user_data.get('role') != 'admin': # Admin can login from any device
                    device_ids = user_data.get('device_ids', [])
                    max_devices = int(user_data.get('max_devices', 1))
                    
                    if device_id not in device_ids:
                        if len(device_ids) < max_devices:
                            # Still have room, auto-link
                            device_ids.append(device_id)
                            user_data['device_ids'] = device_ids
                            save_users(users)
                        else:
                            # Mismatch and limit reached, create approval request
                            approvals = load_approvals()
                            approvals[username] = {
                                "username": username,
                                "new_device_id": device_id,
                                "time": time.strftime('%Y-%m-%d %H:%M:%S')
                            }
                            save_approvals(approvals)
                            error = t['device_locked_msg']
                            return render_template('login.html', error=error)

                from datetime import datetime
                today = datetime.now().strftime('%Y-%m-%d')
                
                # Check if subscription is valid
                if user_data['start_date'] <= today <= user_data['end_date']:
                    session['username'] = username
                    session['role'] = user_data.get('role', 'user')
                    session.permanent = True  # Enable 30-min timeout
                    session.pop('login_attempts', None)
                    return redirect(url_for('dashboard'))
                else:
                    error = t['subscription_expired']
            else:
                attempts = session.get('login_attempts', 0) + 1
                session['login_attempts'] = attempts
                if attempts >= 3:
                    session['lockout_until'] = time.time() + 60
                    error = t['lockout_msg']
                else:
                    error = t['wrong_password']
        else:
            attempts = session.get('login_attempts', 0) + 1
            session['login_attempts'] = attempts
            if attempts >= 3:
                session['lockout_until'] = time.time() + 60
                error = t['lockout_msg']
            else:
                error = t['user_not_found']
            
    return render_template('login.html', error=error)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    users = load_users()
    logs = load_logs()
    msg = None
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add' or action == 'edit':
            target_user = request.form.get('new_user') if action == 'add' else request.form.get('target_user')
            new_pass = request.form.get('new_pass')
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            role = request.form.get('role', 'user')
            amount = request.form.get('amount', '0')
            max_devices = int(request.form.get('max_devices', 1))
            
            if target_user and new_pass:
                # Hash the password before saving
                hashed_password = generate_password_hash(new_pass)
                
                # Maintain existing device_ids if editing
                existing_ids = users.get(target_user, {}).get('device_ids', []) if action == 'edit' else []
                
                users[target_user] = {
                    "password": hashed_password,
                    "start_date": start_date or "2024-01-01",
                    "end_date": end_date or "2025-01-01",
                    "role": role,
                    "amount": amount,
                    "max_devices": max_devices,
                    "device_ids": existing_ids
                }
                save_users(users)
                log_activity(session.get('username'), f"{'إضافة' if action == 'add' else 'تعديل'} المستخدم: {target_user} (الأجهزة: {max_devices})")
                msg = f"تم {'إضافة' if action == 'add' else 'تعديل'} المستخدم {target_user} بنجاح."
        
        elif action == 'delete':
            target_user = request.form.get('target_user')
            if target_user and target_user != session.get('username'):
                user_backup = users[target_user]
                del users[target_user]
                save_users(users)
                log_activity(session.get('username'), f"حذف المستخدم: {target_user}", {"restore_data": user_backup, "restore_username": target_user})
                msg = f"تم حذف المستخدم {target_user}."
        
        elif action == 'restore':
            log_id = int(request.form.get('log_id', -1))
            full_logs = load_logs() # Load in correct order (oldest first for index)
            if 0 <= log_id < len(full_logs):
                log_entry = full_logs[log_id]
                if log_entry.get('extra_data') and 'restore_data' in log_entry['extra_data']:
                    rest_user = log_entry['extra_data']['restore_username']
                    users[rest_user] = log_entry['extra_data']['restore_data']
                    save_users(users)
                    log_activity(session.get('username'), f"استعادة المستخدم: {rest_user}")
                    msg = f"تم استعادة المستخدم {rest_user} بنجاح."

        elif action == 'approve_device' or action == 'reject_device':
            target_user = request.form.get('target_user')
            approvals = load_approvals()
            if target_user in approvals:
                if action == 'approve_device':
                    new_device_id = approvals[target_user]['new_device_id']
                    if 'device_ids' not in users[target_user]:
                        users[target_user]['device_ids'] = []
                    
                    if new_device_id not in users[target_user]['device_ids']:
                        users[target_user]['device_ids'].append(new_device_id)
                        
                    save_users(users)
                    log_activity(session.get('username'), f"الموافقة على جهاز جديد للمستخدم: {target_user}")
                    msg = f"تم الموافقة على الجهاز الجديد للمستخدم {target_user}."
                else:
                    log_activity(session.get('username'), f"رفض جهاز جديد للمستخدم: {target_user}")
                    msg = f"تم رفض طلب الجهاز للمستخدم {target_user}."
                del approvals[target_user]
                save_approvals(approvals)

        elif action == 'reset_devices':
            target_user = request.form.get('target_user')
            if target_user in users:
                users[target_user]['device_ids'] = []
                save_users(users)
                log_activity(session.get('username'), f"إعادة ضبط أجهزة المستخدم: {target_user}")
                msg = f"تم مسح جميع الأجهزة المرتبطة بالمستخدم {target_user}."

    # For display, we need logs in reverse but with their original IDs
    display_logs = []
    full_logs_raw = load_logs()
    for idx, log in enumerate(full_logs_raw):
        log_copy = log.copy()
        log_copy['id'] = idx
        display_logs.append(log_copy)

    approvals = load_approvals()
    return render_template('admin.html', users=users, logs=display_logs[::-1], msg=msg, approvals=approvals)

@app.route('/api/change_password', methods=['POST'])
def change_password():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    data = request.json
    new_password = data.get('new_password')
    username = session['username']
    
    if not new_password or len(new_password) < 3:
        return {"error": "كلمة السر قصيرة جداً."}, 400
        
    users = load_users()
    if username in users:
        users[username]['password'] = generate_password_hash(new_password)
        save_users(users)
        log_activity(username, "تغيير كلمة السر الخاصة")
        return {"status": "success", "message": "تم تغيير كلمة السر بنجاح."}
    
    return {"error": "فشل تغيير كلمة السر."}, 400

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=session['username'])

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/api/set_key', methods=['POST'])
def set_key():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    data = request.json
    api_key = data.get('api_key')
    if api_key:
        session['groq_api_key'] = api_key
        return {"status": "success", "message": "تم حفظ مفتاح Groq الخاص بك بنجاح."}
    return {"error": "No key provided"}, 400

def get_market_status():
    """Checks if US market is open and returns (is_open, message)"""
    try:
        now = pd.Timestamp.now(tz='America/New_York')
        open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
        is_weekday = now.dayofweek < 5
        
        if is_weekday and open_time <= now <= close_time:
            return True, ""
            
        next_open = open_time
        if now > close_time or not is_weekday:
            next_open += pd.Timedelta(days=1)
            
        while next_open.dayofweek >= 5: # Skip weekends
            next_open += pd.Timedelta(days=1)
            
        days_ar = {0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة"}
        day_name = days_ar[next_open.dayofweek]
        
        next_open_ksa = next_open.tz_convert('Asia/Riyadh')
        time_str = next_open_ksa.strftime("%I:%M").lstrip("0")
        ampm = "صباحاً" if next_open_ksa.hour < 12 else "مساءً"
        msg = f"السوق الأمريكي مغلق حالياً. سيفتح يوم {day_name} الساعة {time_str} {ampm} بتوقيت السعودية."
    except Exception as e:
        msg = "تنبيه: السوق الأمريكي قد يكون مغلقاً حالياً."
        return False, msg
        
    return False, msg

@app.route('/api/chat', methods=['POST'])
def chat():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    # Rate limiting check
    if not check_rate_limit(session['username']):
        return {"response": "<div style='color:#e74c3c;padding:10px;'>⚠️ لقد تجاوزت الحد الأقصى للطلبات (20/دقيقة). انتظر قليلاً وحاول مرة أخرى.</div>"}
    
    lang = session.get('lang', 'ar')
    t = get_translations(lang)
    data = request.json
    user_message = data.get('message', '')
    timeframe = data.get('timeframe', '15m')
    
    # Map timeframe to valid yfinance period
    timeframe_to_period = {
        "15m": "5d",
        "30m": "10d",
        "1h": "1mo",
        "1d": "1y",
        "1mo": "5y"
    }
    
    # Map timeframe to Arabic title
    timeframe_titles = {
        "15m": "لحظي (15 دقيقة)",
        "30m": "لحظي (30 دقيقة)",
        "1h": "لحظي (ساعة)",
        "1d": "يومي",
        "1mo": "شهري"
    }
    
    period = timeframe_to_period.get(timeframe, "1y")
    tf_title = timeframe_titles.get(timeframe, "يومي")
    
    # 1. Extract Ticker - Enhanced with Arabic stock name support
    import re
    # Keywords to ignore (common technical terms that might look like tickers)
    IGNORED_KEYWORDS = ['LSTM', 'BERT', 'AI', 'MACD', 'RSI', 'EMA', 'SMA', 'ATR']
    
    # Map common index abbreviations to their yfinance ticker symbols
    TICKER_MAP = {
        'NDQ': 'NQ=F',      # Nasdaq 100 Futures
        'NDX': '^NDX',       # Nasdaq 100 Index
        'SPX': '^SPX',       # S&P 500 Index
        'DOW': '^DJI',       # Dow Jones Industrial Average
        'DJI': '^DJI',
        'VIX': '^VIX',       # Volatility Index
        'QQQ': 'QQQ',        # Nasdaq ETF
        'SPY': 'SPY'         # S&P 500 ETF
    }
    
    # Arabic stock name to ticker mapping for beginners
    ARABIC_STOCK_MAP = {
        'تسلا': 'TSLA', 'تيسلا': 'TSLA',
        'ابل': 'AAPL', 'آبل': 'AAPL', 'أبل': 'AAPL', 'ايفون': 'AAPL',
        'مايكروسوفت': 'MSFT', 'مايكرو': 'MSFT', 'ويندوز': 'MSFT',
        'جوجل': 'GOOG', 'قوقل': 'GOOG', 'غوغل': 'GOOG', 'الفابت': 'GOOG',
        'امازون': 'AMZN', 'أمازون': 'AMZN',
        'ميتا': 'META', 'فيسبوك': 'META', 'فيس': 'META',
        'انفيديا': 'NVDA', 'نفيديا': 'NVDA', 'إنفيديا': 'NVDA',
        'ايه ام دي': 'AMD',
        'ناسداك': 'NQ=F', 'النسداق': 'NQ=F', 'النازداك': 'NQ=F',
        'اس اند بي': 'SPY', 'اس بي': 'SPY',
        'بوينج': 'BA', 'بوينغ': 'BA',
        'ديزني': 'DIS',
        'نتفلكس': 'NFLX', 'نتفليكس': 'NFLX',
        'سوني': 'SONY',
        'اوبر': 'UBER',
        'كوين': 'COIN', 'كوين بيس': 'COIN',
    }
    
    # Try Arabic name first
    ticker = None
    for ar_name, ar_ticker in ARABIC_STOCK_MAP.items():
        if ar_name in user_message:
            ticker = ar_ticker
            break
    
    # Then try English ticker symbol
    if not ticker:
        ticker_match = re.search(r'\b[A-Z]{2,5}\b', user_message)
        potential_ticker = ticker_match.group(0) if ticker_match else None
        
        if potential_ticker and potential_ticker not in IGNORED_KEYWORDS:
            ticker = TICKER_MAP.get(potential_ticker, potential_ticker)
    
    if not ticker and 'last_ticker' in session:
        ticker = session['last_ticker']

    if ticker:
        session['last_ticker'] = ticker
        
    is_open, market_msg = get_market_status()
    market_alert = ""
    if not is_open and timeframe in ['15m', '30m', '1h']:
        market_alert = f"<div style='background: rgba(255, 152, 0, 0.1); border-right: 4px solid #ff9800; padding: 12px; border-radius: 8px; margin-bottom: 20px; color: #ffb74d; box-shadow: 0 4px 15px rgba(0,0,0,0.2);'><b><i class='fas fa-exclamation-triangle'></i> تنبيه:</b> {market_msg}<br><span style='font-size: 0.9em; opacity: 0.8;'>البيانات الظاهرة تعكس آخر إغلاق متاح للتحليل اللحظي.</span></div>"
    
    response = ""
    
    try:
        # Enhanced intent detection with colloquial Arabic support
        msg_lower = user_message.lower()
        
        # Scanner keywords (looking for opportunities)
        scanner_keywords = ["عطني سهم", "عطني اسهم", "توصيات", "فرص", "اعطني", "ابحث", 
                           "وش افضل", "وش أفضل", "ايش افضل", "أفضل سهم", "فرصة",
                           "سهم حلو", "سهم زين", "اسهم ايجابية", "أسهم إيجابية",
                           "ارشحلي", "نصحني", "positive", "scan", "opportunities"]
        
        is_scanner_request = any(kw in user_message for kw in scanner_keywords)
        # Don't treat as scanner if they have a specific ticker with توصية
        if is_scanner_request and "توصية" in user_message and ticker is not None:
            is_scanner_request = False
        
        # Comparison keywords
        compare_keywords = ["قارن", "مقارنة", "compare", "vs", "ضد", "مقابل", "ولا"]
        is_compare = any(kw in user_message for kw in compare_keywords)
        
        # Sector heatmap keywords
        sector_keywords = ["قطاع", "قطاعات", "sector", "sectors", "هيت ماب", "خريطة"]
        is_sector = any(kw in user_message for kw in sector_keywords)
        
        # Greeting keywords
        greeting_keywords = ["مرحبا", "هلا", "السلام", "أهلا", "اهلا", "هاي", "مساء", "صباح",
                            "hello", "hi", "hey", "مرحب"]
        is_greeting = any(kw in user_message for kw in greeting_keywords)
        
        # Help keywords  
        help_keywords = ["مساعدة", "كيف", "شرح", "وش يعني", "ايش يعني", "ما معنى",
                        "help", "how", "explain", "شلون", "كيف استخدم"]
        is_help = any(kw in user_message for kw in help_keywords)
        
        if is_greeting and not ticker:
            pass  # Handled below
        elif is_help and not ticker:
            help_response = """<div style='background: rgba(212,175,55,0.08); border: 1px solid rgba(212,175,55,0.2); border-radius: 12px; padding: 20px;'>
            <h3 style='color: var(--primary-gold); margin: 0 0 15px 0;'><i class='fas fa-book-open'></i> دليل الاستخدام السريع</h3>
            <div style='display: grid; gap: 10px;'>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #2ecc71;'>📊 تقرير شامل:</b> اكتب رمز السهم فقط (مثل TSLA أو تسلا)
                </div>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #3498db;'>📈 تحليل فني:</b> اكتب "تحليل فني AAPL" أو "حلل ابل"
                </div>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #9b59b6;'>🧠 توقع ذكي:</b> اكتب "توقع NVDA" أو "رأيك في انفيديا"
                </div>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #e67e22;'>🎯 توصية تداول:</b> اكتب "توصية TSLA" أو "عطني توصية تسلا"
                </div>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #2ecc71;'>🔍 بحث عن فرص:</b> اكتب "عطني سهم" أو "ابحث عن فرص"
                </div>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #f1c40f;'>📋 عقود خيارات:</b> اكتب "خيارات AAPL" أو "أوبشن تسلا"
                </div>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #3498db;'>⚖️ مقارنة أسهم:</b> اكتب "قارن AAPL MSFT" أو "قارن تسلا انفيديا"
                </div>
                <div style='background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;'>
                    <b style='color: #1abc9c;'>🗺️ خريطة القطاعات:</b> اكتب "قطاعات" أو "sector"
                </div>
            </div>
            <p style='margin-top: 15px; color: #aaa; font-size: 0.85rem;'>💡 <b>نصيحة:</b> يمكنك الكتابة بالعربي أو الإنجليزي. مثلاً "تسلا" = "TSLA"</p>
            </div>"""
            return {"response": help_response}
        elif is_sector and not ticker:
            # Sector Heatmap
            sector_etfs = {
                'XLK': '💻 تكنولوجيا', 'XLF': '🏦 مالي', 'XLE': '⛽ طاقة',
                'XLV': '💊 صحة', 'XLY': '🛍️ استهلاكي', 'XLI': '🏭 صناعي',
                'XLP': '🥫 أساسيات', 'XLU': '⚡ خدمات', 'XLRE': '🏠 عقاري',
                'XLC': '📡 اتصالات', 'XLB': '🧱 مواد'
            }
            sector_html = ""
            sector_items = []
            for etf, name in sector_etfs.items():
                try:
                    d = get_cached_market_data(etf, "5d")
                    if d is not None and len(d) >= 2:
                        chg = ((d['Close'].iloc[-1] - d['Close'].iloc[-2]) / d['Close'].iloc[-2]) * 100
                        sector_items.append((name, chg, etf))
                except:
                    pass
            
            sector_items.sort(key=lambda x: x[1], reverse=True)
            
            grid = ""
            for name, chg, etf in sector_items:
                bg = f'rgba(38,166,154,{min(abs(chg)*0.15, 0.4)})' if chg >= 0 else f'rgba(239,83,80,{min(abs(chg)*0.15, 0.4)})'
                color = '#26a69a' if chg >= 0 else '#ef5350'
                arrow = '▲' if chg >= 0 else '▼'
                grid += f"""<div style="background:{bg};padding:12px;border-radius:10px;text-align:center;border:1px solid {color}22;">
                    <div style="font-size:0.85em;color:#ddd;margin-bottom:4px;">{name}</div>
                    <div style="font-size:1.2em;font-weight:700;color:{color};">{arrow} {chg:+.2f}%</div>
                    <div style="font-size:0.7em;color:#888;margin-top:2px;">{etf}</div>
                </div>"""
            
            response = f"""
            <div style="background:rgba(0,0,0,0.2);border-radius:16px;padding:20px;border:1px solid rgba(212,175,55,0.15);">
                <h3 style="color:#d4af37;margin:0 0 15px 0;">🗺️ خريطة القطاعات — أداء اليوم</h3>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">
                    {grid}
                </div>
                <div style="margin-top:12px;text-align:center;font-size:0.75em;color:#666;">
                    اكتب اسم أي سهم من القطاع لتحليله 📊
                </div>
            </div>"""
            return {"response": response}
        elif is_compare:
            # Stock comparison: extract two tickers
            all_tickers = re.findall(r'\b[A-Z]{2,5}\b', user_message)
            # Also check Arabic names
            for ar_name, ar_ticker in ARABIC_STOCK_MAP.items():
                if ar_name in user_message and ar_ticker not in all_tickers:
                    all_tickers.append(ar_ticker)
            all_tickers = [t for t in all_tickers if t not in IGNORED_KEYWORDS][:2]
            
            if len(all_tickers) < 2:
                return {"response": "<div style='text-align:center;padding:20px;'><i class='fas fa-balance-scale' style='font-size:2rem;color:#d4af37;display:block;margin-bottom:10px;'></i><h4 style='color:#fff;'>⚖️ مقارنة الأسهم</h4><p style='color:#aaa;'>اكتب سهمين للمقارنة، مثل:</p><div style='margin-top:10px;'><code style='background:rgba(212,175,55,0.1);padding:6px 14px;border-radius:8px;color:#d4af37;'>قارن AAPL MSFT</code></div></div>"}
            
            t1, t2 = all_tickers[0], all_tickers[1]
            try:
                e1, e2 = StockEngine(t1), StockEngine(t2)
                h1 = e1.get_market_data(period="1mo")
                h2 = e2.get_market_data(period="1mo")
                h1 = e1.calculate_technical_indicators(h1) if h1 is not None and not h1.empty else h1
                h2 = e2.calculate_technical_indicators(h2) if h2 is not None and not h2.empty else h2
                
                def get_val(info, key, default="N/A"):
                    v = info.get(key, default)
                    if v is None: return default
                    return v
                
                def fmt_num(v):
                    if v == "N/A" or v is None: return "N/A"
                    if isinstance(v, (int, float)):
                        if abs(v) >= 1e12: return f"${v/1e12:.2f}T"
                        if abs(v) >= 1e9: return f"${v/1e9:.2f}B"
                        if abs(v) >= 1e6: return f"${v/1e6:.1f}M"
                        return f"${v:,.2f}"
                    return str(v)
                
                p1 = get_val(e1.info, 'currentPrice', get_val(e1.info, 'regularMarketPrice', 0))
                p2 = get_val(e2.info, 'currentPrice', get_val(e2.info, 'regularMarketPrice', 0))
                pe1 = get_val(e1.info, 'trailingPE')
                pe2 = get_val(e2.info, 'trailingPE')
                mc1 = fmt_num(get_val(e1.info, 'marketCap'))
                mc2 = fmt_num(get_val(e2.info, 'marketCap'))
                
                rsi1 = f"{h1['RSI'].iloc[-1]:.1f}" if h1 is not None and 'RSI' in h1 and not h1.empty else "N/A"
                rsi2 = f"{h2['RSI'].iloc[-1]:.1f}" if h2 is not None and 'RSI' in h2 and not h2.empty else "N/A"
                
                macd_s1 = "صعودي 🟢" if (h1 is not None and 'MACD' in h1 and 'Signal_Line' in h1 and h1['MACD'].iloc[-1] > h1['Signal_Line'].iloc[-1]) else "هبوطي 🔴"
                macd_s2 = "صعودي 🟢" if (h2 is not None and 'MACD' in h2 and 'Signal_Line' in h2 and h2['MACD'].iloc[-1] > h2['Signal_Line'].iloc[-1]) else "هبوطي 🔴"
                
                vol1 = fmt_num(get_val(e1.info, 'averageVolume'))
                vol2 = fmt_num(get_val(e2.info, 'averageVolume'))
                div1 = f"{get_val(e1.info, 'dividendYield', 0)*100:.2f}%" if get_val(e1.info, 'dividendYield', 0) not in [0, "N/A", None] else "لا يوجد"
                div2 = f"{get_val(e2.info, 'dividendYield', 0)*100:.2f}%" if get_val(e2.info, 'dividendYield', 0) not in [0, "N/A", None] else "لا يوجد"
                
                n1 = get_val(e1.info, 'shortName', t1)
                n2 = get_val(e2.info, 'shortName', t2)
                
                # Determine winner
                score1, score2 = 0, 0
                try:
                    if float(pe1) < float(pe2): score1 += 1
                    else: score2 += 1
                except: pass
                try:
                    if float(rsi1) < float(rsi2): score1 += 1
                    else: score2 += 1
                except: pass
                if "صعودي" in macd_s1: score1 += 1
                if "صعودي" in macd_s2: score2 += 1
                
                winner = t1 if score1 > score2 else t2 if score2 > score1 else "تعادل"
                w_color = "#2ecc71" if winner != "تعادل" else "#f1c40f"
                
                compare_html = f"""
                <div style="background:linear-gradient(135deg,rgba(212,175,55,0.06),rgba(0,0,0,0.3));border:1px solid rgba(212,175,55,0.2);border-radius:14px;padding:20px;margin-bottom:12px;">
                    <h3 style="color:#d4af37;margin:0 0 15px 0;text-align:center;"><i class="fas fa-balance-scale"></i> مقارنة: {t1} ⚡ {t2}</h3>
                    <table style="width:100%;border-collapse:collapse;font-size:0.85em;">
                        <thead><tr style="border-bottom:2px solid rgba(212,175,55,0.3);">
                            <th style="padding:10px;color:#888;text-align:right;">المقياس</th>
                            <th style="padding:10px;color:#d4af37;text-align:center;">{t1}<br><span style="font-size:0.75em;color:#888;">{n1}</span></th>
                            <th style="padding:10px;color:#3498db;text-align:center;">{t2}<br><span style="font-size:0.75em;color:#888;">{n2}</span></th>
                        </tr></thead>
                        <tbody>
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;color:#aaa;">💰 السعر</td><td style="padding:8px;text-align:center;color:#fff;font-weight:bold;">${p1}</td><td style="padding:8px;text-align:center;color:#fff;font-weight:bold;">${p2}</td></tr>
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);background:rgba(255,255,255,0.02);"><td style="padding:8px;color:#aaa;">📊 P/E</td><td style="padding:8px;text-align:center;color:#fff;">{pe1}</td><td style="padding:8px;text-align:center;color:#fff;">{pe2}</td></tr>
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;color:#aaa;">💎 القيمة السوقية</td><td style="padding:8px;text-align:center;color:#fff;">{mc1}</td><td style="padding:8px;text-align:center;color:#fff;">{mc2}</td></tr>
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);background:rgba(255,255,255,0.02);"><td style="padding:8px;color:#aaa;">📉 RSI</td><td style="padding:8px;text-align:center;color:{'#ef5350' if rsi1!='N/A' and float(rsi1)>70 else '#26a69a' if rsi1!='N/A' and float(rsi1)<30 else '#fff'};">{rsi1}</td><td style="padding:8px;text-align:center;color:{'#ef5350' if rsi2!='N/A' and float(rsi2)>70 else '#26a69a' if rsi2!='N/A' and float(rsi2)<30 else '#fff'};">{rsi2}</td></tr>
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;color:#aaa;">📈 MACD</td><td style="padding:8px;text-align:center;">{macd_s1}</td><td style="padding:8px;text-align:center;">{macd_s2}</td></tr>
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);background:rgba(255,255,255,0.02);"><td style="padding:8px;color:#aaa;">📊 متوسط الحجم</td><td style="padding:8px;text-align:center;color:#fff;">{vol1}</td><td style="padding:8px;text-align:center;color:#fff;">{vol2}</td></tr>
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;color:#aaa;">💵 توزيعات</td><td style="padding:8px;text-align:center;color:#fff;">{div1}</td><td style="padding:8px;text-align:center;color:#fff;">{div2}</td></tr>
                            <tr style="background:rgba(212,175,55,0.08);"><td style="padding:10px;color:#d4af37;font-weight:bold;">🏆 الحكم</td><td colspan="2" style="padding:10px;text-align:center;font-weight:bold;font-size:1.1em;color:{w_color};">{'⚖️ تعادل — كلاهما جيد' if winner=='تعادل' else f'✅ {winner} أفضل فنياً ({max(score1,score2)}/3)'}</td></tr>
                        </tbody>
                    </table>
                </div>"""
                return {"response": compare_html}
            except Exception as e:
                return {"response": f"<div style='color:#ef5350;padding:15px;'>❌ خطأ في المقارنة: {str(e)}</div>"}
        elif is_scanner_request:
            pass  # Scanner handled below
        elif not ticker:
            friendly_msg = """<div style='text-align: center; padding: 20px;'>
            <i class='fas fa-search' style='font-size: 2rem; color: var(--primary-gold); margin-bottom: 15px; display: block;'></i>
            <h4 style='color: #fff; margin-bottom: 10px;'>🔎 حدد السهم اللي تبي تحلله</h4>
            <p style='color: #aaa; font-size: 0.9rem; margin-bottom: 15px;'>اكتب رمز السهم بالإنجليزي أو اسمه بالعربي</p>
            <div style='display: flex; gap: 8px; justify-content: center; flex-wrap: wrap;'>
                <span style='background: rgba(212,175,55,0.1); padding: 5px 12px; border-radius: 15px; font-size: 0.8rem; color: var(--primary-gold);'>TSLA أو تسلا</span>
                <span style='background: rgba(212,175,55,0.1); padding: 5px 12px; border-radius: 15px; font-size: 0.8rem; color: var(--primary-gold);'>AAPL أو ابل</span>
                <span style='background: rgba(212,175,55,0.1); padding: 5px 12px; border-radius: 15px; font-size: 0.8rem; color: var(--primary-gold);'>NVDA أو انفيديا</span>
            </div>
            </div>"""
            return {"response": friendly_msg}

        # Initialize Engine if we have a ticker or if we are scanning (scanner creates its own engines)
        if ticker:
            engine = StockEngine(ticker)
            hist = engine.get_market_data()
            
            if hist is None or hist.empty:
                 return {"response": f"<div style='text-align:center;padding:20px;'><i class='fas fa-exclamation-circle' style='font-size:2rem;color:#e74c3c;'></i><h4 style='color:#fff;margin-top:10px;'>❗ لم أتمكن من جلب بيانات للسهم {ticker}</h4><p style='color:#aaa;'>تأكد من الرمز وحاول مرة أخرى</p></div>"}
                 
        # Determine intent - Enhanced with colloquial Arabic
        fundamental_keywords = ["تحليل أساسي", "البيانات المالية", "أساسي", "مالي", "ارباح", "أرباح", "قوائم مالية", "fundamental"]
        technical_keywords = ["تحليل فني", "المؤشرات الفنية", "لحظي", "مضاربة", "ارتداد", "انعكاس", "قصير", "حلل", "فني", "شارت", "تشارت", "chart", "technical", "حركة السعر"]
        ai_keywords = ["توقع", "ذكاء", "مستشار", "رأيك", "رايك", "وش رايك", "ايش رايك", "شو رايك", "prediction", "ai", "تنبؤ", "نظرتك"]
        signal_keywords = ["توصية", "عطني توصية", "اشارة", "إشارة", "signal", "سيجنال"]
        options_keywords = ["عقود الخيارات", "عقود", "خيارات", "أوبشن", "اوبشن", "options", "option", "كول", "بوت"]
        
        if any(kw in user_message for kw in fundamental_keywords):
            is_halal, reason = engine.screen_shariah_compliance()
            info = engine.info
            
            def fmt_num(val, prefix='', suffix='', decimals=2):
                if val is None or val == 'N/A':
                    return 'N/A'
                try:
                    num = float(val)
                    if abs(num) >= 1e12: return f"{prefix}{num/1e12:.{decimals}f}T{suffix}"
                    elif abs(num) >= 1e9: return f"{prefix}{num/1e9:.{decimals}f}B{suffix}"
                    elif abs(num) >= 1e6: return f"{prefix}{num/1e6:.{decimals}f}M{suffix}"
                    else: return f"{prefix}{num:.{decimals}f}{suffix}"
                except: return str(val)
            
            def clr(val, good, bad, lower=False):
                try:
                    v = float(val)
                    if lower:
                        return '#26a69a' if v <= good else '#ef5350' if v >= bad else '#fff'
                    else:
                        return '#26a69a' if v >= good else '#ef5350' if v <= bad else '#fff'
                except: return '#fff'
            
            pe = info.get('trailingPE', None)
            fwd_pe = info.get('forwardPE', None)
            pb = info.get('priceToBook', None)
            eps_val = info.get('trailingEps', None)
            revenue = info.get('totalRevenue', None)
            profit_margin = info.get('profitMargins', None)
            debt_equity = info.get('debtToEquity', None)
            dividend_yield = info.get('dividendYield', None)
            beta_v = info.get('beta', None)
            market_cap = info.get('marketCap', None)
            avg_volume = info.get('averageVolume', None)
            week52_high = info.get('fiftyTwoWeekHigh', None)
            week52_low = info.get('fiftyTwoWeekLow', None)
            roe = info.get('returnOnEquity', None)
            revenue_growth = info.get('revenueGrowth', None)
            earnings_growth = info.get('earningsGrowth', None)
            current_ratio = info.get('currentRatio', None)
            free_cashflow = info.get('freeCashflow', None)
            company_name = info.get('longName', ticker)
            sector = info.get('sector', 'N/A')
            industry = info.get('industry', 'N/A')
            curr_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
            
            # Fundamental Score
            fs = 50
            if pe and pe > 0:
                if pe < 15: fs += 10
                elif pe < 25: fs += 5
                elif pe > 40: fs -= 10
            if profit_margin and profit_margin > 0.15: fs += 10
            elif profit_margin and profit_margin < 0: fs -= 15
            if debt_equity and debt_equity < 50: fs += 10
            elif debt_equity and debt_equity > 150: fs -= 10
            if roe and roe > 0.15: fs += 10
            elif roe and roe < 0: fs -= 10
            if dividend_yield and dividend_yield > 0.02: fs += 5
            if revenue_growth and revenue_growth > 0.1: fs += 5
            if current_ratio and current_ratio > 1.5: fs += 5
            fs = max(0, min(100, fs))
            fc = '#26a69a' if fs >= 70 else '#f0c040' if fs >= 40 else '#ef5350'
            
            w52 = ''
            if week52_high and week52_low:
                try:
                    rng = week52_high - week52_low
                    if rng > 0 and curr_price:
                        w52 = f" ({((curr_price - week52_low) / rng) * 100:.0f}% من النطاق)"
                except: pass
            
            def rw(label, value, icon='', vc='#fff'):
                return f"<tr style='border-bottom:1px solid rgba(255,255,255,0.05);'><td style='padding:10px 12px;color:#d4af37;font-weight:600;white-space:nowrap;'>{icon} {label}</td><td style='padding:10px 12px;color:{vc};font-weight:500;text-align:left;'>{value}</td></tr>"
            
            response = f"""
            <div style="margin-bottom:12px;">
                <table style="width:100%;border-collapse:collapse;background:linear-gradient(135deg,#111827,#0f172a);border-radius:12px;overflow:hidden;border:1px solid rgba(212,175,55,0.2);font-size:0.88em;" dir="rtl">
                    <thead>
                        <tr style="background:linear-gradient(135deg,#d4af37,#aa8529);">
                            <th colspan="2" style="padding:14px;color:#000;font-size:1.1em;text-align:center;">
                                📋 التحليل الأساسي الشامل — {company_name} ({ticker})
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {rw('الشركة / القطاع', f'{sector} — {industry}', '🏢')}
                        {rw('السعر الحالي', f'${curr_price:.2f}' if curr_price else 'N/A', '💲', '#fff')}
                        {rw('القيمة السوقية', fmt_num(market_cap, '$'), '💎')}
                        {rw('مكرر الأرباح P/E', f'{pe:.1f}' if pe else 'N/A', '📊', clr(pe, 20, 40, True) if pe else '#fff')}
                        {rw('مكرر الأرباح المستقبلي', f'{fwd_pe:.1f}' if fwd_pe else 'N/A', '🔮', clr(fwd_pe, 18, 35, True) if fwd_pe else '#fff')}
                        {rw('السعر / القيمة الدفترية P/B', f'{pb:.2f}' if pb else 'N/A', '📚', clr(pb, 3, 8, True) if pb else '#fff')}
                        {rw('ربحية السهم EPS', f'${eps_val:.2f}' if eps_val else 'N/A', '💵', '#26a69a' if eps_val and eps_val > 0 else '#ef5350')}
                        {rw('الإيرادات', fmt_num(revenue, '$'), '📈')}
                        {rw('نمو الإيرادات', f'{revenue_growth*100:.1f}%' if revenue_growth else 'N/A', '🚀', clr(revenue_growth, 0.1, 0, False) if revenue_growth else '#fff')}
                        {rw('نمو الأرباح', f'{earnings_growth*100:.1f}%' if earnings_growth else 'N/A', '📊', clr(earnings_growth, 0.1, -0.1, False) if earnings_growth else '#fff')}
                        {rw('هامش الربح', f'{profit_margin*100:.1f}%' if profit_margin else 'N/A', '✂️', clr(profit_margin, 0.15, 0, False) if profit_margin else '#fff')}
                        {rw('العائد على حقوق الملكية ROE', f'{roe*100:.1f}%' if roe else 'N/A', '🏦', clr(roe, 0.15, 0.05, False) if roe else '#fff')}
                        {rw('نسبة الدين/حقوق الملكية', f'{debt_equity:.0f}%' if debt_equity else 'N/A', '⚖️', clr(debt_equity, 50, 150, True) if debt_equity else '#fff')}
                        {rw('النسبة الجارية', f'{current_ratio:.2f}' if current_ratio else 'N/A', '💧', clr(current_ratio, 1.5, 1, False) if current_ratio else '#fff')}
                        {rw('التدفق النقدي الحر', fmt_num(free_cashflow, '$'), '💰', '#26a69a' if free_cashflow and free_cashflow > 0 else '#ef5350')}
                        {rw('توزيعات الأرباح', f'{dividend_yield*100:.2f}%' if dividend_yield else 'لا يوجد', '🎁', '#26a69a' if dividend_yield and dividend_yield > 0 else '#888')}
                        {rw('معامل بيتا β', f'{beta_v:.2f}' if beta_v else 'N/A', '📉')}
                        {rw('نطاق 52 أسبوع', f'${week52_low:.2f} — ${week52_high:.2f}{w52}' if week52_high and week52_low else 'N/A', '📏')}
                        {rw('متوسط حجم التداول', fmt_num(avg_volume), '📊')}
                        <tr style="background:rgba(212,175,55,0.08);">
                            <td style="padding:12px;color:#d4af37;font-weight:700;">⭐ قوة الأساسيات</td>
                            <td style="padding:12px;text-align:left;">
                                <div style="display:flex;align-items:center;gap:10px;">
                                    <div style="flex:1;height:10px;background:rgba(255,255,255,0.1);border-radius:5px;overflow:hidden;">
                                        <div style="width:{fs}%;height:100%;background:{fc};border-radius:5px;transition:width 1s;"></div>
                                    </div>
                                    <b style="color:{fc};font-size:1.2em;">{fs}/100</b>
                                </div>
                            </td>
                        </tr>
                        <tr style="background:rgba(255,255,255,0.02);">
                            <td style="padding:12px;color:#d4af37;font-weight:600;">🕌 الوضع الشرعي</td>
                            <td style="padding:12px;color:{'#26a69a' if is_halal else '#ef5350'};font-weight:600;">{reason} {'✅' if is_halal else '❌'}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            """
            
        elif any(kw in user_message for kw in technical_keywords):
            
            # Use dynamic UI timeframe
            hist = engine.get_market_data(period=period, interval=timeframe)
            
            if hist is None or hist.empty:
                return {"response": f"❌ لا توجد بيانات كافية للتحليل الفني لسهم **{ticker}** حالياً."}
                
            hist = engine.calculate_technical_indicators(hist)
            rec_signal, levels = engine.get_recommendation(hist)
            latest = hist.iloc[-1]
            
            # Generate Professional Multi-Subplot Chart
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, 
                               vertical_spacing=0.03, 
                               subplot_titles=(f'تحليل {ticker} - {tf_title}', 'Volume', 'RSI (14)', 'MACD'),
                               row_width=[0.2, 0.2, 0.15, 0.45])

            # 1. Main Candlestick Chart (Row 1)
            fig.add_trace(go.Candlestick(x=hist.index,
                            open=hist['Open'], high=hist['High'],
                            low=hist['Low'], close=hist['Close'], 
                            name='Price', showlegend=True), row=1, col=1)
            
            # Add EMAs
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA20'], name='EMA 20', line=dict(color='#ff9900', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA50'], name='EMA 50', line=dict(color='#0066ff', width=1.5)), row=1, col=1)
            
            # Add Bollinger Bands
            fig.add_trace(go.Scatter(x=hist.index, y=hist['BB_Upper'], name='BB Upper', line=dict(color='rgba(173, 216, 230, 0.3)', width=1, dash='dot'), showlegend=False), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['BB_Lower'], name='BB Lower', line=dict(color='rgba(173, 216, 230, 0.3)', width=1, dash='dot'), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.05)', showlegend=False), row=1, col=1)

            # 2. Volume (Row 2)
            colors = ['red' if row['Open'] > row['Close'] else 'green' for index, row in hist.iterrows()]
            fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], name='Volume', marker_color=colors, showlegend=False), row=2, col=1)

            # 3. RSI (Row 3)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['RSI'], name='RSI', line=dict(color='#af7ac5', width=2), showlegend=False), row=3, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="rgba(255,0,0,0.5)", row=3, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="rgba(0,255,0,0.5)", row=3, col=1)

            # 4. MACD (Row 4)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MACD'], name='MACD', line=dict(color='#3498db', width=1.5), showlegend=False), row=4, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['Signal_Line'], name='Signal', line=dict(color='#e67e22', width=1.5), showlegend=False), row=4, col=1)
            
            macd_hist_colors = ['red' if val < 0 else 'green' for val in (hist['MACD'] - hist['Signal_Line'])]
            fig.add_trace(go.Bar(x=hist.index, y=hist['MACD'] - hist['Signal_Line'], name='MACD Hist', marker_color=macd_hist_colors, showlegend=False), row=4, col=1)

            # Add Trade Levels to Main Chart
            if levels:
                if 'TP' in levels:
                    fig.add_hline(y=levels['TP'], line_dash="dash", line_color="#2ecc71", annotation_text="Target", row=1, col=1)
                if 'SL' in levels:
                    fig.add_hline(y=levels['SL'], line_dash="dash", line_color="#e74c3c", annotation_text="Stop Loss", row=1, col=1)
                if 'Entry' in levels:
                    fig.add_hline(y=levels['Entry'], line_dash="dot", line_color="#ffffff", annotation_text="Entry", row=1, col=1)
                
                # Add Support & Resistance zones
                if 'Resistance' in levels and not pd.isna(levels['Resistance']):
                    fig.add_hline(y=levels['Resistance'], line_dash="solid", line_color="rgba(231, 76, 60, 0.2)", line_width=3, annotation_text="Resistance", row=1, col=1)
                if 'Support' in levels and not pd.isna(levels['Support']):
                    fig.add_hline(y=levels['Support'], line_dash="solid", line_color="rgba(46, 204, 113, 0.2)", line_width=3, annotation_text="Support", row=1, col=1)

            fig.update_layout(
                template="plotly_dark",
                height=900,
                margin=dict(l=50, r=50, t=50, b=50),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='white', size=12),
                xaxis_rangeslider_visible=False,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            # Update Y axes for better scaling
            fig.update_yaxes(title_text="Price", row=1, col=1)
            fig.update_yaxes(title_text="Volume", row=2, col=1)
            fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
            fig.update_yaxes(title_text="MACD", row=4, col=1)

            chart_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
            
            # Format Trade Levels in a Unified Table
            tp_val = f"${levels['TP']:.2f}" if levels and 'TP' in levels else "غير متوفر"
            sl_val = f"${levels['SL']:.2f}" if levels and 'SL' in levels else "غير متوفر"
            entry_val = f"${levels['Entry']:.2f}" if levels and 'Entry' in levels else "غير متوفر"
            res_val = f"${levels['Resistance']:.2f}" if levels and 'Resistance' in levels and not pd.isna(levels['Resistance']) else "غير متوفر"
            sup_val = f"${levels['Support']:.2f}" if levels and 'Support' in levels and not pd.isna(levels['Support']) else "غير متوفر"
            
            rsi_warn = ""
            if latest['RSI'] > 70:
                rsi_warn = f"<br><span style='color: #ff4d4d; font-size: 0.9em;'>⚠️ تشبع شرائي - قد ينعكس هبوطاً</span>"
            elif latest['RSI'] < 30:
                rsi_warn = f"<br><span style='color: #2ecc71; font-size: 0.9em;'>✅ تشبع بيعي - قد يرتد صعوداً</span>"

            # Calculate missing fields for Intraday
            is_halal, shariah_reason = engine.screen_shariah_compliance()
            
            # Expected Profit and R/R calculation
            expected_profit_pct = "0.00%"
            risk_reward_ratio = "1:2" # Default
            if levels and 'Entry' in levels and 'TP' in levels and 'SL' in levels:
                entry = levels['Entry']
                tp = levels['TP']
                sl = levels['SL']
                if entry > 0:
                    profit_pct = abs((tp - entry) / entry) * 100
                    expected_profit_pct = f"{profit_pct:.2f}%"
                    
                    risk = abs(entry - sl)
                    reward = abs(tp - entry)
                    if risk > 0:
                        risk_reward_ratio = f"1:{reward/risk:.1f}"

            # Hold time rule for intraday
            hold_time_rules = {
                "15m": "15 إلى 45 دقيقة",
                "30m": "30 إلى 90 دقيقة",
                "1h": "ساعة إلى 3 ساعات",
                "1d": "يوم إلى 5 أيام",
                "1mo": "شهر إلى 6 أشهر"
            }
            max_hold = hold_time_rules.get(timeframe, "حسب الاستراتيجية")

            import datetime
            gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            rec_class = 'buy' if 'شراء' in rec_signal else 'sell' if 'بيع' in rec_signal else 'hold'

            # Position Sizing (Pro Feature)
            capital = 10000 # Default example capital
            risk_pct = 1.0 # Standard 1% risk
            shares, pos_value = 0, 0
            if levels and 'Entry' in levels and 'SL' in levels:
                shares, pos_value = engine.calculate_position_size(capital, risk_pct, levels['Entry'], levels['SL'])
            
            fund_score = engine.calculate_fundamental_score()

            table_html = f"""
            <table style="width: 100%; border-collapse: collapse; margin-top: 15px; background-color: #222; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.3); text-align: right;" dir="rtl">
                <thead>
                    <tr style="background: linear-gradient(135deg, #d4af37, #aa8529); color: #000;">
                        <th colspan="2" style="padding: 10px; font-size: 1.05rem; text-align: center;">📈 التحليل الفني الشامل: {ticker} ({tf_title})</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; width: 40%; color: #d4af37;">الشركة / السهم</td>
                        <td style="padding: 10px;">{engine.info.get('longName', ticker)}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">السعر الحالي</td>
                        <td style="padding: 10px;">${latest['Close']:.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">إشارة التداول</td>
                        <td style="padding: 10px; font-weight: bold;" class="recommendation-box {rec_class}">{rec_signal}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">أمر الدخول / الوقف / الهدف</td>
                        <td style="padding: 10px; font-weight: bold;">
                            <span style="color: #3498db;">دخول: {entry_val}</span> | 
                            <span style="color: #ff4d4d;">وقف: {sl_val}</span> | 
                            <span style="color: #2ecc71;">هدف: {tp_val}</span>
                        </td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">إدارة المخاطر (لـ $10k)</td>
                        <td style="padding: 10px; color: #f1c40f;">
                            اشتري <strong>{shares} سهم</strong> (بقيمة ${pos_value:,.2f})<br>
                            <small style="color: #aaa;">*مخاطرة 1% من رأس المال ($100)</small>
                        </td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">قوة الأساسيات (0-100)</td>
                        <td style="padding: 10px; font-weight: bold; color: {'#2ecc71' if fund_score > 60 else '#f1c40f' if fund_score > 40 else '#e74c3c'};">
                            {fund_score} / 100
                        </td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">الدعم / المقاومة</td>
                        <td style="padding: 10px;">{sup_val} / {res_val}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">📐 ATR (تقلب يومي)</td>
                        <td style="padding: 10px; color: #aaa;">${latest.get('ATR', 0):.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">⚖️ Risk/Reward</td>
                        <td style="padding: 10px; color: {'#26a69a' if levels and 'TP' in levels and 'SL' in levels and 'Entry' in levels and (levels['TP']-levels['Entry']) > 0 and (levels['Entry']-levels['SL']) > 0 and (levels['TP']-levels['Entry'])/(levels['Entry']-levels['SL']) >= 2 else '#f0c040' if levels and 'TP' in levels and 'SL' in levels and 'Entry' in levels and (levels['TP']-levels['Entry']) > 0 and (levels['Entry']-levels['SL']) > 0 else '#888'}; font-weight: bold;">
                            {f"1:{((levels['TP']-levels['Entry'])/(levels['Entry']-levels['SL'])):.1f}" if levels and 'TP' in levels and 'SL' in levels and 'Entry' in levels and (levels['Entry']-levels['SL']) > 0 else 'N/A'}
                        </td>
                    </tr>
                    <tr style="border-bottom: 1px solid #444;">
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">الأساسيات ونسبة التطهير</td>
                        <td style="padding: 10px; color: #f39c12; font-weight: bold;">{shariah_reason}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; font-weight: bold; color: #d4af37;">وقت إصدار التحليل</td>
                        <td style="padding: 10px; font-size: 0.85rem; color: #aaa;">{gen_time}</td>
                    </tr>
                </tbody>
            </table>
            """

            # Smart Score — combines technical + fundamental into a visual gauge
            tech_score = 50
            try:
                r = latest.get('RSI', 50)
                if r < 30: tech_score += 15
                elif r < 45: tech_score += 8
                elif r > 70: tech_score -= 15
                elif r > 55: tech_score -= 5
                
                if latest.get('MACD', 0) > latest.get('Signal_Line', 0): tech_score += 12
                else: tech_score -= 8
                
                if latest['Close'] > latest.get('EMA20', latest['Close']): tech_score += 8
                else: tech_score -= 5
                
                if latest.get('ADX', 0) > 25: tech_score += 5
                
                if latest['Close'] > latest.get('VWAP', latest['Close']): tech_score += 5
                else: tech_score -= 3
                
                if latest.get('Stoch_K', 50) < 20: tech_score += 5
                elif latest.get('Stoch_K', 50) > 80: tech_score -= 5
            except: pass
            tech_score = max(0, min(100, tech_score))
            
            smart_score = int((tech_score * 0.6) + (fund_score * 0.4))
            ss_color = '#26a69a' if smart_score >= 70 else '#f0c040' if smart_score >= 45 else '#ef5350'
            ss_label = 'شراء قوي 🟢' if smart_score >= 75 else 'شراء 🟢' if smart_score >= 60 else 'انتظار 🟡' if smart_score >= 45 else 'تجنب 🔴'
            
            # SVG Gauge
            pct = smart_score / 100
            dash = 251.2 * pct
            gap = 251.2 * (1 - pct)
            
            # Volume trend
            try:
                vol_avg = hist['Volume'].rolling(20).mean().iloc[-1]
                vol_now = hist['Volume'].iloc[-1]
                vol_ratio = vol_now / vol_avg if vol_avg > 0 else 1
                vol_label = 'مرتفع ↑' if vol_ratio > 1.3 else 'منخفض ↓' if vol_ratio < 0.7 else 'عادي'
                vol_clr = '#26a69a' if vol_ratio > 1.3 else '#ef5350' if vol_ratio < 0.7 else '#888'
            except:
                vol_label = 'N/A'
                vol_clr = '#888'
            
            adx_val = latest.get('ADX', 0)
            adx_label = 'قوي' if adx_val > 25 else 'ضعيف'
            macd_trend = 'صعودي' if latest.get('MACD', 0) > latest.get('Signal_Line', 0) else 'هبوطي'
            macd_clr = '#26a69a' if macd_trend == 'صعودي' else '#ef5350'
            
            smart_card = f"""
            <div style="background:linear-gradient(135deg,rgba(212,175,55,0.06),rgba(0,0,0,0.4));border:1px solid rgba(212,175,55,0.2);border-radius:16px;padding:20px;margin-bottom:15px;">
                <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;">
                    <div style="text-align:center;flex-shrink:0;">
                        <svg width="90" height="90" viewBox="0 0 100 100">
                            <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="8"/>
                            <circle cx="50" cy="50" r="40" fill="none" stroke="{ss_color}" stroke-width="8" stroke-dasharray="{dash:.1f} {gap:.1f}" stroke-dashoffset="62.8" stroke-linecap="round" style="transition:all 1s;"/>
                            <text x="50" y="47" text-anchor="middle" fill="{ss_color}" font-size="22" font-weight="bold">{smart_score}</text>
                            <text x="50" y="62" text-anchor="middle" fill="#888" font-size="8">SCORE</text>
                        </svg>
                    </div>
                    <div style="flex:1;min-width:200px;">
                        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                            <h3 style="margin:0;color:#fff;font-size:1.1rem;">{engine.info.get('longName', ticker)}</h3>
                            <span style="background:{ss_color};color:#000;padding:3px 12px;border-radius:12px;font-size:0.78em;font-weight:700;">{ss_label}</span>
                        </div>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;">
                            <span style="background:rgba(255,255,255,0.04);padding:4px 10px;border-radius:8px;font-size:0.75em;color:{'#ef5350' if latest.get('RSI',50)>70 else '#26a69a' if latest.get('RSI',50)<30 else '#aaa'};">RSI {latest.get('RSI',0):.0f}</span>
                            <span style="background:rgba(255,255,255,0.04);padding:4px 10px;border-radius:8px;font-size:0.75em;color:{macd_clr};">MACD {macd_trend}</span>
                            <span style="background:rgba(255,255,255,0.04);padding:4px 10px;border-radius:8px;font-size:0.75em;color:#aaa;">ADX {adx_val:.0f} ({adx_label})</span>
                            <span style="background:rgba(255,255,255,0.04);padding:4px 10px;border-radius:8px;font-size:0.75em;color:{vol_clr};">Vol {vol_label}</span>
                        </div>
                    </div>
                </div>
            </div>
            """
            
            response = f"{market_alert}\n{smart_card}\n{table_html}"
            
            return {"response": response, "chart": chart_json}
            
        elif any(kw in user_message for kw in ai_keywords):
             # AI Analysis
            hist = engine.get_market_data(period=period, interval=timeframe)
            if hist is None or hist.empty:
                return {"response": f"❌ لا توجد بيانات كافية للتحليل بناء على الإطار الزمني المختار لسهم **{ticker}** حالياً."}

            hist = engine.calculate_technical_indicators(hist)
            is_halal, reason = engine.screen_shariah_compliance()
            
            # Use the AI Analyzer with session key
            api_key = session.get('groq_api_key') or DEFAULT_API_KEY
            analyzer = AIAnalyzer(api_key=api_key) 
            response = analyzer.get_ai_insight(ticker, engine.info, hist, reason, tf_title=tf_title, timeframe_val=timeframe, lang=lang)
            
        elif any(kw in user_message for kw in signal_keywords) and ticker:
            # New Options Trade Signal Card
            hist = engine.get_market_data(period=period, interval=timeframe)
            if hist is None or hist.empty:
                return {"response": f"❌ لا توجد بيانات كافية لتوليد توصية لسهم **{ticker}** حالياً."}
            
            hist = engine.calculate_technical_indicators(hist)
            options_data = engine.get_options_data()
            current_price = hist['Close'].iloc[-1]
            
            api_key = session.get('groq_api_key') or DEFAULT_API_KEY
            analyzer = AIAnalyzer(api_key=api_key)
            
            ai_card = analyzer.get_options_trade_signal(ticker, current_price, options_data, hist, tf_title=tf_title, timeframe_val=timeframe)
            
            options_stats_html = ""
            if options_data:
                options_stats_html = f"""
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px;">
                    <div style="background: #333; padding: 8px; border-radius: 5px;">
                        <strong>أقرب تاريخ استحقاق:</strong> {options_data['expirationDate']}
                    </div>
                    <div style="background: #333; padding: 8px; border-radius: 5px;">
                        <strong>P/C Ratio:</strong> {options_data.get('putCallRatioVol', 0):.2f}
                    </div>
                    <div style="background: #333; padding: 8px; border-radius: 5px;">
                        <strong>أحجام الـ Call:</strong> {int(options_data.get('callVolume', 0)):,}
                    </div>
                    <div style="background: #333; padding: 8px; border-radius: 5px;">
                        <strong>أحجام الـ Put:</strong> {int(options_data.get('putVolume', 0)):,}
                    </div>
                </div>
                """

            response = (
                f"{market_alert}\n"
                f"<h3>🎯 توصية تداول لسهم {ticker} مبنية على تحليل الخيارات والمؤشرات:</h3>\n"
                f"{options_stats_html}\n"
                f"{ai_card}\n\n"
                f"⚠️ *ملاحظة: هذه توصية آلية مبنية على قراءة أحجام الخيارات والمؤشرات الفنية (RSI/MACD) لحظياً وليست نصيحة مالية قطعية.*"
            )
            
        elif is_scanner_request:
            # If no ticker was in session, engine might not exist
            scan_engine = StockEngine("SPY") if not ticker else engine 
            opportunities = scan_engine.scan_market(period=period, interval=timeframe)
            
            if not opportunities:
                response = f"🔍 قمت بفحص أهم الأسهم على فريم ({tf_title}) ولم أجد فرص **شراء** واضحة حالياً بناءً على المؤشرات الفنية."
            else:
                api_key = session.get('groq_api_key') or DEFAULT_API_KEY
                analyzer = AIAnalyzer(api_key=api_key) 
                # Note: get_opportunities_insight still needs lang update if used, but focusing on main insight
                ai_opportunities_insight = analyzer.get_opportunities_insight(opportunities, tf_title=tf_title, timeframe_val=timeframe)
                
                if ai_opportunities_insight:
                    response = f"🚀 **تحليل الذكاء الاصطناعي للفرص المتاحة ({tf_title}):**\n\n{ai_opportunities_insight}"
                else:
                    response = "🚀 **الفرص المتاحة حالياً (إشارة شراء فنية):**\n\n"
                    for opp in opportunities:
                        response += f"🔹 **{opp['ticker']}** بسعر ${opp['price']:.2f}\n"
                        response += f"   🎯 هدف: ${opp['tp']:.2f} | 🛑 وقف: ${opp['sl']:.2f}\n"
                        response += f"-----------------------------------\n"
                    
                    response += "\n⚠️ *هذه ليست نصيحة مالية، بل تحليل فني آلي.*"
                    
                    
        elif any(kw in user_message for kw in options_keywords):
            if not ticker:
                 return {"response": "الرجاء تحديد اسم السهم (مثل TSLA) لتحليل عقود الخيارات الخاصة به."}
                 
            options_data = engine.get_options_data()
            if not options_data:
                return {"response": f"❌ عذراً، لم أتمكن من العثور على بيانات عقود خيارات متاحة للسهم **{ticker}**."}
            
            # Use AI Analyzer for Options
            api_key = session.get('groq_api_key') or DEFAULT_API_KEY
            analyzer = AIAnalyzer(api_key=api_key)
            
            # We need current price for the AI prompt based on timeframe
            hist = engine.get_market_data(period=period, interval=timeframe)
            if hist is None or hist.empty:
                 return {"response": f"❌ لا توجد بيانات كافية للتحليل بناء على الإطار الزمني المختار لسهم **{ticker}** حالياً."}
                 
            hist = engine.calculate_technical_indicators(hist)
            current_price = hist['Close'].iloc[-1]
            
            ai_insight = analyzer.get_options_insight(ticker, current_price, options_data, hist, tf_title=tf_title)
            
            response = f"""
            {market_alert}
            <h3>📊 تحليل عقود الخيارات: {ticker}</h3>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px;">
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>أقرب تاريخ استحقاق:</strong> {options_data['expirationDate']}
                </div>
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>P/C Ratio (أحجام):</strong> {options_data['putCallRatioVol']:.2f}
                </div>
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>إجمالي أحجام الـ Call:</strong> {int(options_data['callVolume']):,}
                </div>
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>إجمالي أحجام الـ Put:</strong> {int(options_data['putVolume']):,}
                </div>
            </div>

            <div style="background: #222; padding: 10px; border-radius: 5px; font-size: 0.9em; line-height: 1.5;">
                <strong>🧠 قراءة الذكاء الاصطناعي للسوق:</strong><br>
                {ai_insight}
            </div>
            """

        elif is_greeting:
            # Professional greeting with live market data
            username = session.get('username', '')
            hour = datetime.now().hour
            time_greet = 'صباح الخير ☀️' if hour < 12 else 'مساء الخير 🌙' if hour < 18 else 'مساء النور ⭐'
            
            # Quick market pulse
            market_html = ''
            try:
                spx_d = get_cached_market_data("^GSPC", "2d")
                vix_d = get_cached_market_data("^VIX", "1d")
                if spx_d is not None and len(spx_d) >= 2:
                    spx_change = ((spx_d['Close'].iloc[-1] - spx_d['Close'].iloc[-2]) / spx_d['Close'].iloc[-2]) * 100
                    spx_val = spx_d['Close'].iloc[-1]
                    spx_color = '#26a69a' if spx_change >= 0 else '#ef5350'
                    spx_arrow = '▲' if spx_change >= 0 else '▼'
                    vix_val = vix_d['Close'].iloc[-1] if vix_d is not None and len(vix_d) >= 1 else 0
                    vix_color = '#26a69a' if vix_val < 20 else '#f0c040' if vix_val < 30 else '#ef5350'
                    market_html = f"""
                    <div style="display:flex;gap:8px;margin:12px 0;font-size:0.82em;">
                        <div style="flex:1;background:rgba(255,255,255,0.04);padding:8px;border-radius:8px;text-align:center;border:1px solid rgba(255,255,255,0.06);">
                            <span style="color:#aaa;font-size:0.85em;">S&P 500</span><br>
                            <b style="color:{spx_color};">{spx_arrow} {spx_val:,.0f} ({spx_change:+.2f}%)</b>
                        </div>
                        <div style="flex:1;background:rgba(255,255,255,0.04);padding:8px;border-radius:8px;text-align:center;border:1px solid rgba(255,255,255,0.06);">
                            <span style="color:#aaa;font-size:0.85em;">VIX</span><br>
                            <b style="color:{vix_color};">{vix_val:.1f}</b>
                        </div>
                    </div>"""
            except: pass
            
            response = f"""
            <div style="background:linear-gradient(135deg,rgba(212,175,55,0.06),rgba(0,0,0,0.3));border:1px solid rgba(212,175,55,0.2);border-radius:16px;padding:20px;">
                <h3 style="color:#d4af37;margin:0 0 5px 0;">{time_greet} {username}</h3>
                <p style="color:#aaa;margin:0 0 10px 0;font-size:0.9em;">أنا مستشارك الذكي. كيف أقدر أساعدك اليوم؟</p>
                {market_html}
                <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;">
                    <span onclick="document.getElementById('user-input').value='TSLA';sendMessage();" style="background:rgba(212,175,55,0.1);color:#d4af37;padding:5px 12px;border-radius:15px;font-size:0.78em;cursor:pointer;border:1px solid rgba(212,175,55,0.2);">📊 تحليل سهم</span>
                    <span onclick="document.getElementById('user-input').value='ابحث عن فرص';sendMessage();" style="background:rgba(46,204,113,0.1);color:#2ecc71;padding:5px 12px;border-radius:15px;font-size:0.78em;cursor:pointer;border:1px solid rgba(46,204,113,0.2);">🔍 فرص السوق</span>
                    <span onclick="document.getElementById('user-input').value='قارن AAPL MSFT';sendMessage();" style="background:rgba(52,152,219,0.1);color:#3498db;padding:5px 12px;border-radius:15px;font-size:0.78em;cursor:pointer;border:1px solid rgba(52,152,219,0.2);">⚖️ مقارنة</span>
                </div>
            </div>"""
             
        else:
             # Default to Full Report if only ticker is mentioned (or no specific intent detected)
            hist = engine.get_market_data(period=period, interval=timeframe)
            
            if hist is None or hist.empty:
                return {"response": f"❌ لا توجد بيانات كافية للتحليل لحظي لسهم **{ticker}** حالياً."}
                
            hist = engine.calculate_technical_indicators(hist)
            rec_signal, levels = engine.get_recommendation(hist)
            latest = hist.iloc[-1]
            is_halal, compliance_reason = engine.screen_shariah_compliance()
            
            # 1. AI Analysis
            api_key = session.get('groq_api_key') or DEFAULT_API_KEY
            analyzer = AIAnalyzer(api_key=api_key) 
            ai_insight = analyzer.get_ai_insight(ticker, engine.info, hist, compliance_reason, lang=lang)
            
            # 1c. Market Pulse (SPX + VIX context) — using cache
            market_pulse_html = ""
            try:
                spx_d = get_cached_market_data("^GSPC", "2d")
                vix_d = get_cached_market_data("^VIX", "1d")
                
                if len(spx_d) >= 2 and len(vix_d) >= 1:
                    spx_change = ((spx_d['Close'].iloc[-1] - spx_d['Close'].iloc[-2]) / spx_d['Close'].iloc[-2]) * 100
                    spx_color = '#26a69a' if spx_change >= 0 else '#ef5350'
                    spx_arrow = '▲' if spx_change >= 0 else '▼'
                    vix_val = vix_d['Close'].iloc[-1]
                    vix_color = '#26a69a' if vix_val < 20 else '#f0c040' if vix_val < 30 else '#ef5350'
                    vix_label = 'هادئ' if vix_val < 20 else 'حذر' if vix_val < 30 else 'خوف!'
                    
                    market_pulse_html = f"""
                    <div style="display:flex;gap:8px;margin-bottom:10px;font-size:0.82em;">
                        <div style="flex:1;background:rgba(255,255,255,0.04);padding:8px 12px;border-radius:8px;text-align:center;border:1px solid rgba(255,255,255,0.06);">
                            <span style="color:#aaa;">S&P 500</span><br>
                            <b style="color:{spx_color};">{spx_arrow} {spx_change:+.2f}%</b>
                        </div>
                        <div style="flex:1;background:rgba(255,255,255,0.04);padding:8px 12px;border-radius:8px;text-align:center;border:1px solid rgba(255,255,255,0.06);">
                            <span style="color:#aaa;">VIX (الخوف)</span><br>
                            <b style="color:{vix_color};">{vix_val:.1f} — {vix_label}</b>
                        </div>
                    </div>
                    """
            except:
                pass
            
            # 1b. Candlestick Patterns & Fibonacci
            candle_patterns = engine.detect_candlestick_patterns(hist)
            fib_levels = engine.calculate_fibonacci_levels(hist)
            
            # 1d. Multi-Timeframe Analysis (MTF)
            mtf_results = []
            mtf_timeframes = [('1h', '1mo', '⏱️ ساعة'), ('1d', '6mo', '📅 يومي'), ('1wk', '2y', '📆 أسبوعي')]
            for mtf_tf, mtf_period, mtf_label in mtf_timeframes:
                try:
                    mtf_hist = engine.get_market_data(period=mtf_period, interval=mtf_tf)
                    if mtf_hist is not None and len(mtf_hist) >= 20:
                        mtf_hist = engine.calculate_technical_indicators(mtf_hist)
                        mtf_sig, _ = engine.get_recommendation(mtf_hist)
                        mtf_rsi = mtf_hist['RSI'].iloc[-1]
                        mtf_macd = 'صعودي' if mtf_hist['MACD'].iloc[-1] > mtf_hist['Signal_Line'].iloc[-1] else 'هبوطي'
                        mtf_results.append({'label': mtf_label, 'signal': mtf_sig, 'rsi': mtf_rsi, 'macd': mtf_macd})
                except:
                    pass
            
            # 1e. Smart Context Alerts
            smart_alerts = []
            try:
                w52h = engine.info.get('fiftyTwoWeekHigh', 0)
                w52l = engine.info.get('fiftyTwoWeekLow', 0)
                curr = latest['Close']
                if w52h and curr >= w52h * 0.95:
                    smart_alerts.append(('🔝 قريب من أعلى 52 أسبوع!', '#ef5350'))
                if w52l and curr <= w52l * 1.05:
                    smart_alerts.append(('📉 قريب من أدنى 52 أسبوع — فرصة؟', '#26a69a'))
                
                avg_vol = engine.info.get('averageVolume', 0)
                curr_vol = latest.get('Volume', 0) if not pd.isna(latest.get('Volume', 0)) else 0
                if avg_vol > 0 and curr_vol > avg_vol * 2:
                    smart_alerts.append(('🔊 حجم تداول غير اعتيادي (2x+)', '#f0c040'))
                
                if latest.get('RSI', 50) > 75:
                    smart_alerts.append(('⚠️ تشبع شرائي شديد — احذر!', '#ef5350'))
                elif latest.get('RSI', 50) < 25:
                    smart_alerts.append(('💎 تشبع بيعي شديد — فرصة ذهبية!', '#26a69a'))
                
                beta = engine.info.get('beta', 1)
                if beta and beta > 1.5:
                    smart_alerts.append((f'🎢 سهم عالي التقلب (Beta: {beta:.1f})', '#f0c040'))
                
                # RSI Divergence Detection
                if len(hist) >= 10:
                    price_5 = hist['Close'].tail(10)
                    rsi_5 = hist['RSI'].tail(10)
                    price_min_idx = price_5.idxmin()
                    price_max_idx = price_5.idxmax()
                    
                    # Bullish Divergence: price makes lower low, RSI makes higher low
                    if (price_5.iloc[-1] < price_5.iloc[0] and 
                        rsi_5.iloc[-1] > rsi_5.loc[price_min_idx] and
                        rsi_5.iloc[-1] < 45):
                        smart_alerts.append(('📈 دايفرجنس صعودي — RSI يعارض السعر!', '#26a69a'))
                    
                    # Bearish Divergence: price makes higher high, RSI makes lower high
                    if (price_5.iloc[-1] > price_5.iloc[0] and 
                        rsi_5.iloc[-1] < rsi_5.loc[price_max_idx] and
                        rsi_5.iloc[-1] > 55):
                        smart_alerts.append(('📉 دايفرجنس هبوطي — RSI يحذر!', '#ef5350'))
                
                # Analyst Price Target
                target = engine.info.get('targetMeanPrice', None)
                if target and curr > 0:
                    upside = ((target - curr) / curr) * 100
                    t_color = '#26a69a' if upside > 5 else '#ef5350' if upside < -5 else '#f0c040'
                    smart_alerts.append((f'🎯 هدف المحللين: ${target:.0f} ({upside:+.1f}%)', t_color))
                
                # Sector performance context
                sector = engine.info.get('sector', '')
                if sector:
                    smart_alerts.append((f'🏢 القطاع: {sector}', '#888'))
                    
            except:
                pass
            
            # 2. Charts (Expert Technical Chart with Volume)
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.025, subplot_titles=(None, 'RSI (14)', 'MACD', 'حجم التداول'), 
                                row_width=[0.12, 0.15, 0.15, 0.58])

            # Row 1: Main Price Chart (Candlestick + EMAs + Bollinger Bands + VWAP)
            fig.add_trace(go.Candlestick(x=hist.index,
                            open=hist['Open'], high=hist['High'],
                            low=hist['Low'], close=hist['Close'], name='السعر',
                            increasing_line_color='#26a69a', decreasing_line_color='#ef5350'), 
                            row=1, col=1)
            
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA9'], name='EMA 9', line=dict(color='#ff6b6b', width=1, dash='dot')), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA20'], name='EMA 20', line=dict(color='orange', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA50'], name='EMA 50', line=dict(color='#4dabf7', width=1.5)), row=1, col=1)

            # VWAP
            if 'VWAP' in hist.columns:
                fig.add_trace(go.Scatter(x=hist.index, y=hist['VWAP'], name='VWAP', line=dict(color='#ffd43b', width=2, dash='dashdot')), row=1, col=1)

            # Bollinger Bands
            fig.add_trace(go.Scatter(x=hist.index, y=hist['BB_Upper'], name='BB Upper', line=dict(color='rgba(173, 216, 230, 0.4)', width=1, dash='dash')), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['BB_Lower'], name='BB Lower', line=dict(color='rgba(173, 216, 230, 0.4)', width=1, dash='dash'), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.08)'), row=1, col=1)

            if levels:
                if 'TP' in levels:
                    fig.add_hline(y=levels['TP'], line_dash="dash", line_color="green", annotation_text="الهدف", annotation_position="top left", row=1, col=1)
                if 'SL' in levels:
                    fig.add_hline(y=levels['SL'], line_dash="dash", line_color="red", annotation_text="الوقف", annotation_position="bottom left", row=1, col=1)
                if 'Entry' in levels:
                    fig.add_hline(y=levels['Entry'], line_dash="dot", line_color="gray", annotation_text="الدخول", annotation_position="top left", row=1, col=1)
                
                # Support and resistance
                if 'Resistance' in levels and not pd.isna(levels['Resistance']):
                    fig.add_hline(y=levels['Resistance'], line_dash="solid", line_color="rgba(255,0,0,0.3)", line_width=2, annotation_text="مقاومة", annotation_position="left", row=1, col=1)
                if 'Support' in levels and not pd.isna(levels['Support']):
                    fig.add_hline(y=levels['Support'], line_dash="solid", line_color="rgba(0,255,0,0.3)", line_width=2, annotation_text="دعم", annotation_position="left", row=1, col=1)

            # Row 2: RSI
            fig.add_trace(go.Scatter(x=hist.index, y=hist['RSI'], name='RSI', line=dict(color='#9775fa', width=1.5)), row=2, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", line_width=1, row=2, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=1, row=2, col=1)
            fig.add_hrect(y0=30, y1=70, fillcolor="purple", opacity=0.04, layer="below", line_width=0, row=2, col=1)

            # Row 3: MACD
            macd_hist = hist['MACD'] - hist['Signal_Line']
            colors = ['#26a69a' if val >= 0 else '#ef5350' for val in macd_hist]
            fig.add_trace(go.Bar(x=hist.index, y=macd_hist, name='Histogram', marker_color=colors), row=3, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MACD'], name='MACD', line=dict(color='#339af0', width=1.5)), row=3, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['Signal_Line'], name='Signal', line=dict(color='#ff922b', width=1.5)), row=3, col=1)

            # Row 4: Volume
            if 'Volume' in hist.columns:
                vol_colors = ['#26a69a' if hist['Close'].iloc[i] >= hist['Open'].iloc[i] else '#ef5350' for i in range(len(hist))]
                fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], name='حجم التداول', marker_color=vol_colors, opacity=0.7), row=4, col=1)

            # Fibonacci Retracement Lines on main chart
            fib_colors = {'23.6%': '#ff9800', '38.2%': '#2196f3', '50.0%': '#9c27b0', '61.8%': '#f44336', '78.6%': '#4caf50'}
            for level_name, level_val in fib_levels.items():
                if level_name in fib_colors:
                    fig.add_hline(y=level_val, line_dash='dot', line_color=fib_colors[level_name], line_width=1, 
                                 annotation_text=f'Fib {level_name}', annotation_position='right',
                                 annotation_font_size=9, annotation_font_color=fib_colors[level_name],
                                 row=1, col=1)

            # Pivot Points (Classic Floor Trader Method)
            try:
                if len(hist) >= 2:
                    pp_high = hist['High'].iloc[-2]
                    pp_low = hist['Low'].iloc[-2]
                    pp_close = hist['Close'].iloc[-2]
                    pp = (pp_high + pp_low + pp_close) / 3
                    r1 = (2 * pp) - pp_low
                    s1 = (2 * pp) - pp_high
                    r2 = pp + (pp_high - pp_low)
                    s2 = pp - (pp_high - pp_low)
                    
                    pivot_levels = [
                        ('R2', r2, 'rgba(239,83,80,0.6)', 'dashdot'),
                        ('R1', r1, 'rgba(239,83,80,0.4)', 'dash'),
                        ('PP', pp, 'rgba(255,255,255,0.5)', 'solid'),
                        ('S1', s1, 'rgba(46,204,113,0.4)', 'dash'),
                        ('S2', s2, 'rgba(46,204,113,0.6)', 'dashdot'),
                    ]
                    for pname, pval, pcolor, pdash in pivot_levels:
                        fig.add_hline(y=pval, line_dash=pdash, line_color=pcolor, line_width=1,
                                     annotation_text=f'{pname} ${pval:.2f}', annotation_position='left',
                                     annotation_font_size=8, annotation_font_color=pcolor,
                                     row=1, col=1)
            except:
                pass

            # Volume Moving Average (20-period) on Volume chart
            try:
                vol_ma = hist['Volume'].rolling(20).mean()
                fig.add_trace(go.Scatter(x=hist.index, y=vol_ma, name='Vol MA20',
                    line=dict(color='#f0c040', width=1.5, dash='dot')), row=4, col=1)
            except:
                pass

            fig.update_layout(
                title=dict(text=f'التحليل الفني الاحترافي - {ticker} ({tf_title})', font=dict(color='black', size=18)),
                template="plotly_white",
                height=850,
                margin=dict(l=15, r=50, t=50, b=15),
                paper_bgcolor='#ffffff',
                plot_bgcolor='#ffffff',
                font=dict(color='black', size=12),
                xaxis_rangeslider_visible=False,
                xaxis=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', tickfont=dict(color='black')),
                xaxis2=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', tickfont=dict(color='black')),
                xaxis3=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', tickfont=dict(color='black')),
                xaxis4=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', tickfont=dict(color='black')),
                yaxis=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', tickformat=".2f", tickfont=dict(color='black'), side="right"),
                yaxis2=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', range=[0, 100], tickvals=[30, 50, 70], tickfont=dict(color='black'), side="right"),
                yaxis3=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', tickfont=dict(color='black'), side="right"),
                yaxis4=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', tickfont=dict(color='black'), side="right"),
                showlegend=False,
                hovermode='x unified'
            )
            chart_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
            
            # 3. Extract analysis details
            score = levels.get('score', 0)
            trend_strength = levels.get('trend_strength', 'N/A')
            reasons_bull = levels.get('reasons_bull', [])
            reasons_bear = levels.get('reasons_bear', [])
            
            # Price change
            if len(hist) >= 2:
                prev_close = hist.iloc[-2]['Close']
                price_change = latest['Close'] - prev_close
                price_change_pct = (price_change / prev_close) * 100
                change_color = '#26a69a' if price_change >= 0 else '#ef5350'
                change_arrow = '▲' if price_change >= 0 else '▼'
            else:
                price_change = 0
                price_change_pct = 0
                change_color = '#888'
                change_arrow = '—'
            
            # Stochastic values
            stoch_k = f"{latest.get('Stoch_K', 0):.0f}" if not pd.isna(latest.get('Stoch_K', float('nan'))) else 'N/A'
            stoch_d = f"{latest.get('Stoch_D', 0):.0f}" if not pd.isna(latest.get('Stoch_D', float('nan'))) else 'N/A'
            adx_val = f"{latest.get('ADX', 0):.0f}" if not pd.isna(latest.get('ADX', float('nan'))) else 'N/A'
            vwap_val = f"${latest.get('VWAP', 0):.2f}" if 'VWAP' in latest and not pd.isna(latest.get('VWAP', float('nan'))) else 'N/A'
            bb_pos = ''
            if not pd.isna(latest.get('BB_Upper', float('nan'))) and not pd.isna(latest.get('BB_Lower', float('nan'))):
                bb_w = latest['BB_Upper'] - latest['BB_Lower']
                if bb_w > 0:
                    bb_pct = ((latest['Close'] - latest['BB_Lower']) / bb_w) * 100
                    bb_pos = f"{bb_pct:.0f}%"
                else:
                    bb_pos = 'N/A'
            else:
                bb_pos = 'N/A'
            
            # Trade details
            trade_details = ""
            if levels and 'TP' in levels:
                risk = abs(levels['Entry'] - levels['SL'])
                reward = abs(levels['TP'] - levels['Entry'])
                rr_ratio = f"{reward/risk:.1f}" if risk > 0 else "N/A"
                trade_details = f"""
                <div style="margin: 12px 0; background: linear-gradient(135deg, #1a2a1a, #1a1a2a); padding: 15px; border-radius: 10px; border-right: 4px solid {'#26a69a' if 'Buy' in rec_signal else '#ef5350'};">
                    <h4 style="margin: 0 0 10px 0; color: #fff; font-size: 1em;">🎯 مستويات الصفقة</h4>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; text-align: center;">
                        <div style="background: rgba(38,166,154,0.15); padding: 10px; border-radius: 8px;">
                            <div style="color: #aaa; font-size: 0.75em;">الهدف (TP)</div>
                            <div style="color: #26a69a; font-weight: bold; font-size: 1.1em;">${levels['TP']:.2f}</div>
                        </div>
                        <div style="background: rgba(100,149,237,0.15); padding: 10px; border-radius: 8px;">
                            <div style="color: #aaa; font-size: 0.75em;">الدخول</div>
                            <div style="color: #6495ed; font-weight: bold; font-size: 1.1em;">${levels['Entry']:.2f}</div>
                        </div>
                        <div style="background: rgba(239,83,80,0.15); padding: 10px; border-radius: 8px;">
                            <div style="color: #aaa; font-size: 0.75em;">وقف الخسارة (SL)</div>
                            <div style="color: #ef5350; font-weight: bold; font-size: 1.1em;">${levels['SL']:.2f}</div>
                        </div>
                    </div>
                    <div style="text-align: center; margin-top: 8px; color: #ccc; font-size: 0.85em;">
                        📐 نسبة المخاطرة/العائد: <b style="color: #f0c040;">{rr_ratio}:1</b>
                    </div>
                </div>
                """
            
            # Candlestick Patterns HTML
            patterns_html = ""
            if candle_patterns:
                p_items = "".join([f"<div style='background:rgba(255,255,255,0.04);padding:8px 12px;border-radius:8px;margin:4px 0;border-right:3px solid {'#26a69a' if d=='\u0635\u0639\u0648\u062f\u064a' else '#ef5350' if d=='\u0647\u0628\u0648\u0637\u064a' else '#f0c040'};'><b>{n}</b><br><span style='font-size:0.8em;color:#aaa;'>{desc}</span></div>" for n, d, desc in candle_patterns])
                patterns_html = f"""<div style="margin-bottom:12px;"><b style="color:#f0c040;">🕯️ أنماط الشموع اليابانية المكتشفة:</b>{p_items}</div>"""
            
            # Fibonacci HTML
            fib_html = ""
            if fib_levels:
                close_price_val = latest['Close']
                nearest_fib = min(fib_levels.items(), key=lambda x: abs(x[1] - close_price_val))
                fib_items = "".join([f"<span style='display:inline-block;background:rgba(255,255,255,0.05);padding:4px 8px;border-radius:4px;margin:2px;font-size:0.8em;{'border:1px solid #f0c040;' if k==nearest_fib[0] else ''}'>{k}: ${v:.2f}</span>" for k, v in fib_levels.items()])
                fib_html = f"""<div style="margin-bottom:12px;"><b style="color:#f0c040;">📐 مستويات فيبوناتشي:</b><div style="margin-top:5px;">{fib_items}</div><div style="font-size:0.75em;color:#aaa;margin-top:4px;">📍 أقرب مستوى للسعر: <b style="color:#f0c040;">{nearest_fib[0]} (${nearest_fib[1]:.2f})</b></div></div>"""
            
            # Multi-Timeframe HTML
            mtf_html = ""
            if mtf_results:
                mtf_rows = ""
                for m in mtf_results:
                    sig_c = '#26a69a' if 'Buy' in m['signal'] else '#ef5350' if 'Sell' in m['signal'] else '#f0c040'
                    sig_short = '🟢 شراء' if 'Buy' in m['signal'] else '🔴 بيع' if 'Sell' in m['signal'] else '🟡 انتظار'
                    macd_c = '#26a69a' if m['macd'] == 'صعودي' else '#ef5350'
                    rsi_c = '#ef5350' if m['rsi'] > 70 else '#26a69a' if m['rsi'] < 30 else '#aaa'
                    mtf_rows += f"<tr style='border-bottom:1px solid rgba(255,255,255,0.04);'><td style='padding:6px 8px;color:#d4af37;'>{m['label']}</td><td style='padding:6px 8px;color:{sig_c};font-weight:700;'>{sig_short}</td><td style='padding:6px 8px;color:{rsi_c};'>{m['rsi']:.0f}</td><td style='padding:6px 8px;color:{macd_c};'>{m['macd']}</td></tr>"
                mtf_html = f"""
                <div style="margin-bottom:12px;background:rgba(255,255,255,0.02);border-radius:10px;padding:12px;border:1px solid rgba(212,175,55,0.15);">
                    <b style="color:#d4af37;font-size:0.9em;">🔭 تحليل متعدد الأطر الزمنية (MTF)</b>
                    <table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:0.82em;">
                        <thead><tr style="border-bottom:2px solid rgba(212,175,55,0.2);">
                            <th style="padding:5px;color:#888;text-align:right;">الإطار</th>
                            <th style="padding:5px;color:#888;">الإشارة</th>
                            <th style="padding:5px;color:#888;">RSI</th>
                            <th style="padding:5px;color:#888;">MACD</th>
                        </tr></thead>
                        <tbody>{mtf_rows}</tbody>
                    </table>
                </div>"""
            
            # Smart Alerts HTML
            alerts_html = ""
            if smart_alerts:
                alerts_items = "".join([f"<span style='display:inline-block;background:rgba(0,0,0,0.3);border:1px solid {c};color:{c};padding:4px 10px;border-radius:15px;font-size:0.78em;margin:3px;'>{txt}</span>" for txt, c in smart_alerts])
                alerts_html = f"""<div style="margin-bottom:12px;">{alerts_items}</div>"""
            
            bull_html = ""
            bear_html = ""
            if reasons_bull:
                bull_items = "".join([f"<li style='color:#26a69a; margin:3px 0; font-size:0.85em;'>✅ {r}</li>" for r in reasons_bull[:5]])
                bull_html = f"<div style='flex:1;'><b style='color:#26a69a;'>إشارات إيجابية ({len(reasons_bull)})</b><ul style='list-style:none;padding:0;margin:5px 0;'>{bull_items}</ul></div>"
            if reasons_bear:
                bear_items = "".join([f"<li style='color:#ef5350; margin:3px 0; font-size:0.85em;'>⛔ {r}</li>" for r in reasons_bear[:5]])
                bear_html = f"<div style='flex:1;'><b style='color:#ef5350;'>إشارات سلبية ({len(reasons_bear)})</b><ul style='list-style:none;padding:0;margin:5px 0;'>{bear_items}</ul></div>"
            
            # 4a. Build Fundamental Analysis Table
            info = engine.info
            
            def fmt_number(val, prefix='', suffix='', decimals=2):
                if val is None or val == 'N/A':
                    return 'N/A'
                try:
                    num = float(val)
                    if abs(num) >= 1e12:
                        return f"{prefix}{num/1e12:.{decimals}f}T{suffix}"
                    elif abs(num) >= 1e9:
                        return f"{prefix}{num/1e9:.{decimals}f}B{suffix}"
                    elif abs(num) >= 1e6:
                        return f"{prefix}{num/1e6:.{decimals}f}M{suffix}"
                    else:
                        return f"{prefix}{num:.{decimals}f}{suffix}"
                except:
                    return str(val)
            
            def color_val(val, good_thresh, bad_thresh, lower_is_better=False):
                try:
                    v = float(val)
                    if lower_is_better:
                        if v <= good_thresh: return '#26a69a'
                        elif v >= bad_thresh: return '#ef5350'
                    else:
                        if v >= good_thresh: return '#26a69a'
                        elif v <= bad_thresh: return '#ef5350'
                except:
                    pass
                return '#fff'
            
            pe = info.get('trailingPE', None)
            fwd_pe = info.get('forwardPE', None)
            pb = info.get('priceToBook', None)
            eps = info.get('trailingEps', None)
            revenue = info.get('totalRevenue', None)
            profit_margin = info.get('profitMargins', None)
            debt_equity = info.get('debtToEquity', None)
            dividend_yield = info.get('dividendYield', None)
            beta_val = info.get('beta', None)
            market_cap = info.get('marketCap', None)
            avg_volume = info.get('averageVolume', None)
            week52_high = info.get('fiftyTwoWeekHigh', None)
            week52_low = info.get('fiftyTwoWeekLow', None)
            roe = info.get('returnOnEquity', None)
            company_name = info.get('longName', ticker)
            sector = info.get('sector', 'N/A')
            industry = info.get('industry', 'N/A')
            
            # Fundamental Score (0-100)
            fund_score = 50
            if pe and pe > 0:
                if pe < 15: fund_score += 10
                elif pe < 25: fund_score += 5
                elif pe > 40: fund_score -= 10
            if profit_margin and profit_margin > 0.15: fund_score += 10
            elif profit_margin and profit_margin < 0: fund_score -= 15
            if debt_equity and debt_equity < 50: fund_score += 10
            elif debt_equity and debt_equity > 150: fund_score -= 10
            if roe and roe > 0.15: fund_score += 10
            elif roe and roe < 0: fund_score -= 10
            if dividend_yield and dividend_yield > 0.02: fund_score += 5
            fund_score = max(0, min(100, fund_score))
            
            if fund_score >= 70: fund_color = '#26a69a'
            elif fund_score >= 40: fund_color = '#f0c040'
            else: fund_color = '#ef5350'
            
            # 52-week position
            w52_pos = ''
            if week52_high and week52_low:
                try:
                    w52_range = week52_high - week52_low
                    if w52_range > 0:
                        w52_pct = ((latest['Close'] - week52_low) / w52_range) * 100
                        w52_pos = f" ({w52_pct:.0f}% من النطاق)"
                except: pass
            
            def row_html(label, value, icon='', val_color='#fff'):
                return f"<tr style='border-bottom:1px solid rgba(255,255,255,0.05);'><td style='padding:10px 12px;color:#d4af37;font-weight:600;white-space:nowrap;'>{icon} {label}</td><td style='padding:10px 12px;color:{val_color};font-weight:500;text-align:left;'>{value}</td></tr>"
            
            fundamental_table = f"""
            <div style="margin-bottom:12px;">
                <table style="width:100%;border-collapse:collapse;background:linear-gradient(135deg,#111827,#0f172a);border-radius:12px;overflow:hidden;border:1px solid rgba(212,175,55,0.2);font-size:0.88em;" dir="rtl">
                    <thead>
                        <tr style="background:linear-gradient(135deg,#d4af37,#aa8529);">
                            <th colspan="2" style="padding:12px;color:#000;font-size:1.05em;text-align:center;">
                                📋 التحليل الأساسي — {company_name}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {row_html('الشركة / القطاع', f'{sector} — {industry}', '🏢')}
                        {row_html('القيمة السوقية', fmt_number(market_cap, '$'), '💎')}
                        {row_html('مكرر الأرباح P/E', f'{pe:.1f}' if pe else 'N/A', '📊', color_val(pe, 20, 40, True) if pe else '#fff')}
                        {row_html('مكرر الأرباح المستقبلي', f'{fwd_pe:.1f}' if fwd_pe else 'N/A', '🔮', color_val(fwd_pe, 18, 35, True) if fwd_pe else '#fff')}
                        {row_html('السعر / القيمة الدفترية P/B', f'{pb:.2f}' if pb else 'N/A', '📚', color_val(pb, 3, 8, True) if pb else '#fff')}
                        {row_html('ربحية السهم EPS', f'${eps:.2f}' if eps else 'N/A', '💵', '#26a69a' if eps and eps > 0 else '#ef5350')}
                        {row_html('الإيرادات', fmt_number(revenue, '$'), '📈')}
                        {row_html('هامش الربح', f'{profit_margin*100:.1f}%' if profit_margin else 'N/A', '✂️', color_val(profit_margin, 0.15, 0, False) if profit_margin else '#fff')}
                        {row_html('العائد على حقوق الملكية ROE', f'{roe*100:.1f}%' if roe else 'N/A', '🏦', color_val(roe, 0.15, 0.05, False) if roe else '#fff')}
                        {row_html('نسبة الدين/حقوق الملكية', f'{debt_equity:.0f}%' if debt_equity else 'N/A', '⚖️', color_val(debt_equity, 50, 150, True) if debt_equity else '#fff')}
                        {row_html('توزيعات الأرباح', f'{dividend_yield*100:.2f}%' if dividend_yield else 'لا يوجد', '💰', '#26a69a' if dividend_yield and dividend_yield > 0 else '#888')}
                        {row_html('معامل بيتا β', f'{beta_val:.2f}' if beta_val else 'N/A', '📉')}
                        {row_html('نطاق 52 أسبوع', f'${week52_low:.2f} — ${week52_high:.2f}{w52_pos}' if week52_high and week52_low else 'N/A', '📏')}
                        {row_html('متوسط حجم التداول', fmt_number(avg_volume), '📊')}
                        <tr style="background:rgba(212,175,55,0.08);">
                            <td style="padding:12px;color:#d4af37;font-weight:700;">⭐ قوة الأساسيات</td>
                            <td style="padding:12px;text-align:left;">
                                <div style="display:flex;align-items:center;gap:10px;">
                                    <div style="flex:1;height:8px;background:rgba(255,255,255,0.1);border-radius:4px;overflow:hidden;">
                                        <div style="width:{fund_score}%;height:100%;background:{fund_color};border-radius:4px;"></div>
                                    </div>
                                    <b style="color:{fund_color};font-size:1.1em;">{fund_score}/100</b>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            """
            
            # 4. Construct Full Response
            rec_class = 'buy' if 'شراء' in rec_signal else 'sell' if 'بيع' in rec_signal else 'hold'
            
            response = f"""
            {market_alert}
            <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); border-radius: 12px; padding: 18px; margin-bottom: 10px; border: 1px solid rgba(240,192,64,0.2);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <h3 style="margin:0; color: #f0c040;">📊 {ticker} — تحليل فني لحظي ({tf_title})</h3>
                    <span style="color: {change_color}; font-weight: bold; font-size: 1.1em;">{change_arrow} {price_change_pct:+.2f}%</span>
                </div>
                
                {market_pulse_html}
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">
                    <div style="background: rgba(255,255,255,0.05); padding: 10px; border-radius: 8px;">
                        <span style="color: #aaa; font-size: 0.8em;">💰 السعر</span><br>
                        <b style="color: #fff; font-size: 1.2em;">${latest['Close']:.2f}</b>
                    </div>
                    <div style="background: rgba(255,255,255,0.05); padding: 10px; border-radius: 8px;">
                        <span style="color: #aaa; font-size: 0.8em;">📈 قوة الاتجاه</span><br>
                        <b style="color: #fff;">{trend_strength}</b>
                    </div>
                </div>
                
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 12px; font-size: 0.85em;">
                    <div style="background: rgba(128,0,128,0.1); padding: 8px; border-radius: 6px; text-align: center;">
                        <span style="color: #aaa;">RSI</span><br>
                        <b style="color: {'#ef5350' if latest['RSI'] > 70 else '#26a69a' if latest['RSI'] < 30 else '#fff'};">{latest['RSI']:.0f}</b>
                    </div>
                    <div style="background: rgba(0,100,200,0.1); padding: 8px; border-radius: 6px; text-align: center;">
                        <span style="color: #aaa;">MACD</span><br>
                        <b style="color: {'#26a69a' if latest['MACD'] > latest['Signal_Line'] else '#ef5350'};">{latest['MACD']:.3f}</b>
                    </div>
                    <div style="background: rgba(255,165,0,0.1); padding: 8px; border-radius: 6px; text-align: center;">
                        <span style="color: #aaa;">Stochastic</span><br>
                        <b style="color: {'#ef5350' if float(stoch_k if stoch_k != 'N/A' else 50) > 80 else '#26a69a' if float(stoch_k if stoch_k != 'N/A' else 50) < 20 else '#fff'};">{stoch_k}</b>
                    </div>
                    <div style="background: rgba(0,200,100,0.1); padding: 8px; border-radius: 6px; text-align: center;">
                        <span style="color: #aaa;">ADX</span><br>
                        <b style="color: #fff;">{adx_val}</b>
                    </div>
                    <div style="background: rgba(100,200,255,0.1); padding: 8px; border-radius: 6px; text-align: center;">
                        <span style="color: #aaa;">VWAP</span><br>
                        <b style="color: {'#26a69a' if latest['Close'] > latest.get('VWAP', latest['Close']) else '#ef5350'};">{vwap_val}</b>
                    </div>
                    <div style="background: rgba(173,216,230,0.1); padding: 8px; border-radius: 6px; text-align: center;">
                        <span style="color: #aaa;">Bollinger</span><br>
                        <b style="color: #fff;">{bb_pos}</b>
                    </div>
                </div>
            </div>
            
            <div class="recommendation-box {rec_class}" style="margin-bottom: 12px; padding: 12px; text-align: center; font-size: 1.1em; border-radius: 10px;">
                {rec_signal}
                <div style="font-size: 0.7em; color: #ccc; margin-top: 4px;">النقاط: {score:.1f}/12</div>
            </div>
            
            {trade_details}
            
            <div style="display: flex; gap: 10px; margin-bottom: 12px;">
                {bull_html}
                {bear_html}
            </div>

            {patterns_html}
            {fib_html}

            {mtf_html}
            {alerts_html}

            {fundamental_table}

            <div style="margin-bottom: 10px; font-size: 0.85em;">
                <strong>الوضع الشرعي:</strong> {compliance_reason} {'✅' if is_halal else '❌'}
            </div>
            
            <div style="background: #1a1a2e; padding: 12px; border-radius: 8px; font-size: 0.9em; line-height: 1.6; border-right: 3px solid #f0c040;">
                <strong>🧠 رأي الذكاء الاصطناعي:</strong><br>
                {ai_insight}
            </div>
            """
            
            return {"response": response, "chart": chart_json}

    except Exception as e:
        logger.error(f"Chat error for {ticker}: {str(e)}")
        response = f"<div style='color:#e74c3c;padding:15px;background:rgba(231,76,60,0.1);border-radius:8px;border:1px solid rgba(231,76,60,0.3);'><i class='fas fa-exclamation-triangle'></i> <b>حدث خطأ أثناء التحليل:</b><br><span style='font-size:0.85em;color:#999;'>{str(e)[:150]}</span><br><br>حاول مرة أخرى أو اختر سهم آخر.</div>"

    return {"response": response}

@app.route('/api/morning_briefing')
def api_morning_briefing():
    """Generates and returns the daily market briefing."""
    try:
        # Get index data
        indices = {"SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI"}
        market_results = {}
        for name, sym in indices.items():
            t = yf.Ticker(sym)
            d = t.history(period="2d")
            if len(d) >= 2:
                change = ((d['Close'].iloc[-1] - d['Close'].iloc[-2]) / d['Close'].iloc[-2]) * 100
                market_results[f"{name.lower()}_change"] = change
        
        sentiment, _ = StockEngine.get_global_sentiment()
        market_results['sentiment'] = sentiment
        
        api_key = session.get('groq_api_key') or DEFAULT_API_KEY
        analyzer = AIAnalyzer(api_key=api_key)
        briefing_html = analyzer.get_market_briefing(market_results)
        
        return {"briefing": briefing_html}
    except Exception as e:
        return {"briefing": f"خطأ في توليد الملخص: {str(e)}"}

@app.route('/api/market_movers')
def api_market_movers():
    """Returns top gainers and losers."""
    gainers, losers = StockEngine.get_market_movers()
    return {"gainers": gainers, "losers": losers}

@app.route('/api/market_status')
def api_market_status():
    """Returns current US market status for the dashboard."""
    is_open, msg = get_market_status()
    sentiment, change = StockEngine.get_global_sentiment()
    gainers, losers = StockEngine.get_market_movers()
    return {
        "is_open": is_open, 
        "message": msg,
        "sentiment": sentiment,
        "sentiment_change": round(change, 2),
        "movers": {"gainers": gainers, "losers": losers}
    }

@app.route('/api/broadcast', methods=['GET', 'POST'])
def broadcast():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    if request.method == 'POST':
        if session.get('role') != 'admin':
            return {"error": "Admin only"}, 403
            
        subject = request.form.get('subject')
        message = request.form.get('message')
        file = request.files.get('file')
        
        file_url = None
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            file_url = f"/static/uploads/{filename}"
            
        ann = load_announcements()
        ann.append({
            "id": len(ann) + 1,
            "subject": subject,
            "message": message,
            "file_url": file_url,
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        save_announcements(ann)
        return {"success": True}
        
    return {"announcements": load_announcements()}

@app.route('/api/support', methods=['GET', 'POST'])
def support_tickets():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    username = session['username']
    tickets = load_tickets()
    
    if request.method == 'POST':
        subject = request.form.get('subject')
        description = request.form.get('description')
        type = request.form.get('type') # Issue/Suggestion
        
        ticket_id = f"T-{secrets.token_hex(4).upper()}"
        tickets[ticket_id] = {
            "id": ticket_id,
            "username": username,
            "subject": subject,
            "description": description,
            "type": type,
            "status": "open",
            "replies": [],
            "last_reply_by": username,
            "rating": None,
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_tickets(tickets)
        return {"success": True, "ticket_id": ticket_id}
        
    # If admin, return all. If user, return only theirs.
    if session.get('role') == 'admin':
        return {"tickets": tickets}
    else:
        user_tickets = {tid: t for tid, t in tickets.items() if t['username'] == username}
        return {"tickets": user_tickets}

@app.route('/api/support/reply', methods=['POST'])
def ticket_reply():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    data = request.json
    ticket_id = data.get('ticket_id')
    message = data.get('message')
    
    tickets = load_tickets()
    if ticket_id in tickets:
        sender = session['username']
        tickets[ticket_id]['replies'].append({
            "user": sender,
            "message": message,
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        tickets[ticket_id]['last_reply_by'] = sender
        save_tickets(tickets)
        return {"success": True}
    return {"error": "Ticket not found"}, 404

@app.route('/api/support/close', methods=['POST'])
def ticket_close():
    if session.get('role') != 'admin':
        return {"error": "Admin only"}, 403
    
    data = request.json
    ticket_id = data.get('ticket_id')
    tickets = load_tickets()
    if ticket_id in tickets:
        tickets[ticket_id]['status'] = 'closed'
        save_tickets(tickets)
        return {"success": True}
    return {"error": "Ticket not found"}, 404

@app.route('/api/support/rate', methods=['POST'])
def ticket_rate():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    data = request.json
    ticket_id = data.get('ticket_id')
    rating = data.get('rating')
    
    tickets = load_tickets()
    if ticket_id in tickets and tickets[ticket_id]['username'] == session['username']:
        tickets[ticket_id]['rating'] = rating
        save_tickets(tickets)
        return {"success": True}
    return {"error": "Unauthorized or not found"}, 404

# --- SQLite Portfolio (replaces JSON) ---

@app.route('/api/portfolio/add', methods=['POST'])
def add_to_portfolio():
    if 'username' not in session:
        return {"success": False, "message": "Login required"}
    
    data = request.json
    username = session['username']
    trade_id = secrets.token_hex(4)
    
    conn = sqlite3.connect(PORTFOLIO_DB)
    c = conn.cursor()
    c.execute('''INSERT INTO trades (id, username, ticker, entry_price, sl, tp, shares, date, status, close_price, pnl)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL, 0)''',
              (trade_id, username, data.get('ticker'), float(data.get('entry_price', 0)),
               float(data.get('sl', 0)), float(data.get('tp', 0)),
               int(data.get('shares', 1)), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return {"success": True, "message": "تمت إضافة الصفقة للمحفظة"}

@app.route('/api/portfolio')
def get_portfolio():
    if 'username' not in session:
        return {"success": False}
    
    username = session['username']
    conn = sqlite3.connect(PORTFOLIO_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM trades WHERE username = ? ORDER BY date DESC', (username,))
    rows = c.fetchall()
    conn.close()
    
    trades = [dict(r) for r in rows]
    
    for trade in trades:
        if trade['status'] == 'open':
            try:
                ticker = yf.Ticker(trade['ticker'])
                current = ticker.fast_info['lastPrice']
                trade['current_price'] = round(current, 2)
                trade['pnl'] = round((current - trade['entry_price']) * trade['shares'], 2)
                trade['pnl_pct'] = round(((current - trade['entry_price']) / trade['entry_price']) * 100, 2)
            except Exception:
                trade['current_price'] = trade['entry_price']
                trade['pnl'] = 0
                trade['pnl_pct'] = 0

    return {"success": True, "trades": trades}

@app.route('/api/portfolio/close', methods=['POST'])
def close_trade():
    if 'username' not in session:
        return {"success": False}
    
    trade_id = request.json.get('id')
    username = session['username']
    
    conn = sqlite3.connect(PORTFOLIO_DB)
    c = conn.cursor()
    c.execute('SELECT * FROM trades WHERE id = ? AND username = ?', (trade_id, username))
    row = c.fetchone()
    
    if row:
        try:
            ticker = yf.Ticker(row[2])  # ticker column
            current = ticker.fast_info['lastPrice']
            pnl = round((current - row[3]) * row[6], 2)  # entry_price * shares
            c.execute('UPDATE trades SET status = ?, close_price = ?, pnl = ? WHERE id = ?',
                      ('closed', current, pnl, trade_id))
        except Exception:
            c.execute('UPDATE trades SET status = ?, close_price = ?, pnl = 0 WHERE id = ?',
                      ('closed', row[3], trade_id))
        conn.commit()
    conn.close()
    return {"success": True}

# --- Real Earnings Calendar ---
@app.route('/api/earnings_calendar')
def earnings_calendar():
    tickers = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'GOOG', 'META', 'AMZN', 'AMD', 'NFLX', 'JPM', 'V', 'UNH']
    earnings = []
    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            earnings_date = None
            
            # Method 1: t.calendar (can be dict or DataFrame)
            try:
                cal = t.calendar
                if isinstance(cal, dict):
                    ed = cal.get('Earnings Date', cal.get('earningsDate', None))
                    if ed:
                        if isinstance(ed, list) and len(ed) > 0:
                            earnings_date = str(ed[0])[:10]
                        else:
                            earnings_date = str(ed)[:10]
                elif cal is not None and hasattr(cal, 'iloc'):
                    if not cal.empty:
                        earnings_date = str(cal.iloc[0, 0])[:10]
            except:
                pass
            
            # Method 2: Fallback to info
            if not earnings_date:
                try:
                    info = t.info
                    ed_ts = info.get('earningsTimestamp', None)
                    if ed_ts:
                        from datetime import datetime as dt
                        earnings_date = dt.fromtimestamp(ed_ts).strftime('%Y-%m-%d')
                    elif 'earningsDate' in info:
                        ed = info['earningsDate']
                        if isinstance(ed, list) and len(ed) > 0:
                            earnings_date = str(ed[0])[:10]
                        else:
                            earnings_date = str(ed)[:10]
                except:
                    pass
            
            if earnings_date and earnings_date != 'None' and earnings_date != 'N':
                earnings.append({'ticker': sym, 'date': earnings_date})
        except Exception:
            pass
    
    earnings.sort(key=lambda x: x.get('date', '9999'))
    return {"success": True, "earnings": earnings}

# --- Backtesting API ---
@app.route('/api/backtest', methods=['POST'])
def backtest():
    if 'username' not in session:
        return {"success": False, "message": "Login required"}
    
    data = request.json
    ticker = data.get('ticker', 'AAPL')
    period = data.get('period', '1y')
    
    try:
        engine = StockEngine(ticker)
        hist = engine.get_market_data(period=period)
        if hist is None or hist.empty:
            return {"success": False, "message": "No data available"}
        hist = engine.calculate_technical_indicators(hist)
        results = engine.backtest_strategy(hist)
        return {"success": True, "ticker": ticker, "period": period, "results": results}
    except Exception as e:
        return {"success": False, "message": str(e)}

# --- Portfolio Analytics API ---
@app.route('/api/portfolio/analytics')
def portfolio_analytics():
    if 'username' not in session:
        return {"success": False}
    
    username = session['username']
    conn = sqlite3.connect(PORTFOLIO_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM trades WHERE username = ? AND status = ?', (username, 'closed'))
    rows = c.fetchall()
    conn.close()
    
    trades = [dict(r) for r in rows]
    if not trades:
        return {"success": True, "metrics": {"error": "No closed trades yet"}}
    
    metrics = StockEngine.calculate_portfolio_metrics(trades)
    return {"success": True, "metrics": metrics}

# --- Auto Paper Trading API ---
@app.route('/api/autotrade/toggle', methods=['POST'])
def autotrade_toggle():
    if 'username' not in session:
        return {"success": False, "error": "Login required"}, 401
    data = request.json or {}
    enable = data.get('enable', True)
    auto_trader.toggle(enable)
    return {"success": True, "enabled": auto_trader.is_enabled()}

@app.route('/api/autotrade/scan', methods=['POST'])
def autotrade_scan():
    if 'username' not in session:
        return {"success": False, "error": "Login required"}, 401
    if not auto_trader.is_enabled():
        return {"success": False, "error": "التداول الآلي غير مفعل"}
    result = auto_trader.scan_and_trade()
    return {"success": True, **result}

@app.route('/api/autotrade/status')
def autotrade_status():
    if 'username' not in session:
        return {"success": False}, 401
    stats = auto_trader.get_stats()
    open_trades = auto_trader.get_open_trades()
    # Update current prices for open trades
    for t in open_trades:
        try:
            eng = StockEngine(t['ticker'])
            h = eng.get_market_data(period="5d")
            if h is not None and not h.empty:
                t['current_price'] = round(h['Close'].iloc[-1], 2)
                t['pnl'] = round((t['current_price'] - t['entry_price']) * t['shares'], 2)
                t['pnl_pct'] = round(((t['current_price'] - t['entry_price']) / t['entry_price']) * 100, 2)
        except:
            pass
    return {"success": True, "stats": stats, "open_trades": open_trades}

@app.route('/api/autotrade/history')
def autotrade_history():
    if 'username' not in session:
        return {"success": False}, 401
    trades = auto_trader.get_all_trades(limit=30)
    return {"success": True, "trades": trades}

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
