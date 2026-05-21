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
            </div>
            <p style='margin-top: 15px; color: #aaa; font-size: 0.85rem;'>💡 <b>نصيحة:</b> يمكنك الكتابة بالعربي أو الإنجليزي. مثلاً "تسلا" = "TSLA"</p>
            </div>"""
            return {"response": help_response}
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
            response = f"""
            📊 **التحليل الأساسي لـ {ticker}:**
            
            - **القطاع:** {engine.info.get('sector', 'N/A')}
            - **الصناعة:** {engine.info.get('industry', 'N/A')}
            - **القيمة السوقية:** ${engine.info.get('marketCap', 0)/1e9:.2f} مليار
            - **مكرر الربحية (P/E):** {engine.info.get('trailingPE', 'N/A')}
            
            **الوضع الشرعي:** {reason} {'✅' if is_halal else '❌'}
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

            
            response = f"{market_alert}\n{table_html}"
            
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
             response = f"{t['welcome_msg']} {session['username']}! {t['bot_intro']}"
             
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
            
            # 2. Charts
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=hist.index,
                            open=hist['Open'], high=hist['High'],
                            low=hist['Low'], close=hist['Close'], name='Price'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA20'], name='EMA 20', line=dict(color='orange', width=1)))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA50'], name='EMA 50', line=dict(color='blue', width=1)))
            
            if levels:
                if 'TP' in levels:
                    fig.add_hline(y=levels['TP'], line_dash="dash", line_color="green", annotation_text="TP", annotation_position="top right")
                if 'SL' in levels:
                    fig.add_hline(y=levels['SL'], line_dash="dash", line_color="red", annotation_text="SL", annotation_position="bottom right")
                if 'Entry' in levels:
                    fig.add_hline(y=levels['Entry'], line_dash="dot", line_color="white", annotation_text="Entry")
                
                # Also add support and resistance to full chart if available
                if 'Resistance' in levels and not pd.isna(levels['Resistance']):
                    fig.add_hline(y=levels['Resistance'], line_dash="solid", line_color="rgba(255,0,0,0.3)", line_width=2, annotation_text="مقاومة")
                if 'Support' in levels and not pd.isna(levels['Support']):
                    fig.add_hline(y=levels['Support'], line_dash="solid", line_color="rgba(0,255,0,0.3)", line_width=2, annotation_text="دعم")

            fig.update_layout(
                title=f'تحليل {ticker} - {tf_title}',
                yaxis_title='السعر',
                template="plotly_dark",
                height=600,
                margin=dict(l=15, r=15, t=50, b=15),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='white', size=13),
                xaxis_rangeslider_visible=False,
                xaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)'),
                yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', tickformat=".2f")
            )
            chart_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
            
            # 3. Trade Levels Formatting
            trade_details = ""
            if levels and 'TP' in levels:
                trade_details = f"""
                <div style="margin: 10px 0; background: #2a2a2a; padding: 10px; border-radius: 5px; border-right: 3px solid {'#28a745' if 'Buy' in rec_signal else '#dc3545'};">
                    <h4 style="margin: 0 0 5px 0; color: #fff;">🎯 أهداف الصفقة</h4>
                    <div style="display: flex; justify-content: space-between; font-size: 0.9em;">
                        <span style="color: #28a745;">ربح: ${levels['TP']:.2f}</span>
                        <span style="color: #dc3545;">وقف: ${levels['SL']:.2f}</span>
                        <span style="color: #17a2b8;">دخول: ${levels['Entry']:.2f}</span>
                    </div>
                </div>
                """
            
            # 4. Construct Full Response
            rec_class = 'buy' if 'شراء' in rec_signal else 'sell' if 'بيع' in rec_signal else 'hold'
            
            response = f"""
            {market_alert}
            <h3>📊 تقرير شامل: {ticker}</h3>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px;">
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>السعر:</strong> ${latest['Close']:.2f}
                </div>
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>P/E:</strong> {engine.info.get('trailingPE', 'N/A')}
                </div>
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>RSI:</strong> {latest['RSI']:.2f}
                </div>
                <div style="background: #333; padding: 8px; border-radius: 5px;">
                    <strong>MACD:</strong> {latest['MACD']:.3f}
                </div>
            </div>

            <div style="margin-bottom: 10px;">
                <strong>الوضع الشرعي:</strong> {compliance_reason} {'✅' if is_halal else '❌'}
            </div>

            {trade_details}
            
            <div class="recommendation-box {rec_class}" style="margin-bottom: 15px;">
                {rec_signal}
            </div>

            <div style="background: #222; padding: 10px; border-radius: 5px; font-size: 0.9em; line-height: 1.5;">
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
    tickers = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'GOOG', 'META', 'AMZN', 'AMD']
    earnings = []
    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            cal = t.calendar
            if cal is not None and not cal.empty:
                date = str(cal.iloc[0, 0]) if hasattr(cal, 'iloc') else str(cal)
                earnings.append({'ticker': sym, 'date': date[:10]})
            else:
                info = t.info
                if 'earningsDate' in info:
                    earnings.append({'ticker': sym, 'date': str(info['earningsDate'])[:10]})
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

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
