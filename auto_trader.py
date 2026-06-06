"""
🤖 Auto Paper Trading Engine — EAGLES OF SPX
Scans the market, opens/closes paper trades automatically.
Virtual capital: $100,000
"""
import sqlite3
import json
import time
import secrets
from datetime import datetime
from stock_engine import StockEngine

DB_PATH = 'portfolio.db'
VIRTUAL_CAPITAL = 100000  # $100K virtual money
MAX_OPEN_TRADES = 5
RISK_PER_TRADE = 0.02  # 2% risk per trade
SCAN_TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOG", "AMD",
    "NFLX", "JPM", "V", "UNH", "HD", "PG", "COST"
]


def init_autotrade_db():
    """Creates the auto_trades table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS auto_trades (
        id TEXT PRIMARY KEY,
        ticker TEXT,
        direction TEXT DEFAULT 'LONG',
        entry_price REAL,
        current_price REAL,
        sl REAL,
        tp REAL,
        shares INTEGER,
        entry_date TEXT,
        close_date TEXT,
        status TEXT DEFAULT 'open',
        pnl REAL DEFAULT 0,
        pnl_pct REAL DEFAULT 0,
        score INTEGER DEFAULT 0,
        reason TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS autotrade_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.commit()
    conn.close()


init_autotrade_db()


def get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM autotrade_settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO autotrade_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def is_enabled():
    return get_setting('auto_enabled', 'false') == 'true'


def toggle(enable=True):
    set_setting('auto_enabled', 'true' if enable else 'false')
    if enable:
        set_setting('start_date', datetime.now().strftime('%Y-%m-%d %H:%M'))
        # Initialize capital if not set
        if not get_setting('current_capital'):
            set_setting('current_capital', str(VIRTUAL_CAPITAL))
            set_setting('starting_capital', str(VIRTUAL_CAPITAL))


def get_open_trades():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM auto_trades WHERE status='open' ORDER BY entry_date DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_all_trades(limit=20):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM auto_trades ORDER BY entry_date DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_stats():
    """Returns performance statistics."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM auto_trades WHERE status='closed'")
    closed = [dict(r) for r in c.fetchall()]
    
    c.execute("SELECT * FROM auto_trades WHERE status='open'")
    open_trades = [dict(r) for r in c.fetchall()]
    conn.close()
    
    total_trades = len(closed)
    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in closed)
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
    avg_win = (sum(t['pnl'] for t in wins) / len(wins)) if wins else 0
    avg_loss = (sum(t['pnl'] for t in losses) / len(losses)) if losses else 0
    
    capital = float(get_setting('current_capital', VIRTUAL_CAPITAL))
    starting = float(get_setting('starting_capital', VIRTUAL_CAPITAL))
    unrealized = 0
    for t in open_trades:
        unrealized += (t['current_price'] - t['entry_price']) * t['shares']
    
    return {
        'enabled': is_enabled(),
        'capital': capital,
        'starting_capital': starting,
        'total_return': ((capital - starting) / starting) * 100,
        'unrealized_pnl': unrealized,
        'total_trades': total_trades,
        'open_trades': len(open_trades),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'wins': len(wins),
        'losses': len(losses),
        'start_date': get_setting('start_date', 'N/A'),
    }


def _analyze_stock(ticker):
    """Analyzes a stock and returns a score + trade setup."""
    try:
        engine = StockEngine(ticker)
        hist = engine.get_market_data(period="1mo", interval="1d")
        if hist is None or hist.empty or len(hist) < 10:
            return None
        
        hist = engine.calculate_technical_indicators(hist)
        latest = hist.iloc[-1]
        
        # Calculate Smart Score
        score = 50
        reasons = []
        
        # RSI
        rsi = latest.get('RSI', 50)
        if rsi < 30:
            score += 15
            reasons.append(f"RSI منخفض ({rsi:.0f})")
        elif rsi < 45:
            score += 8
            reasons.append(f"RSI جيد ({rsi:.0f})")
        elif rsi > 70:
            score -= 15
            reasons.append(f"RSI مرتفع ({rsi:.0f})")
        
        # MACD
        macd = latest.get('MACD', 0)
        signal = latest.get('Signal_Line', 0)
        if macd > signal:
            score += 12
            reasons.append("MACD صعودي")
        else:
            score -= 8
        
        # EMA
        if latest['Close'] > latest.get('EMA20', latest['Close']):
            score += 8
            reasons.append("فوق EMA20")
        else:
            score -= 5
        
        # ADX
        adx = latest.get('ADX', 0)
        if adx > 25:
            score += 5
            reasons.append(f"ADX قوي ({adx:.0f})")
        
        # VWAP
        if latest['Close'] > latest.get('VWAP', latest['Close']):
            score += 5
            reasons.append("فوق VWAP")
        
        # Stochastic
        stoch = latest.get('Stoch_K', 50)
        if stoch < 20:
            score += 5
            reasons.append("Stochastic منخفض")
        elif stoch > 80:
            score -= 5
        
        score = max(0, min(100, score))
        
        # Calculate levels
        rec, levels = engine.get_recommendation(hist)
        
        return {
            'ticker': ticker,
            'score': score,
            'price': latest['Close'],
            'rsi': rsi,
            'macd_bullish': macd > signal,
            'levels': levels,
            'rec': rec,
            'reasons': reasons,
            'name': engine.info.get('shortName', ticker),
        }
    except Exception as e:
        return None


def scan_and_trade():
    """Scans stocks and opens trades for high-scoring opportunities."""
    if not is_enabled():
        return {'action': 'disabled', 'message': 'التداول الآلي معطل'}
    
    open_trades = get_open_trades()
    open_tickers = [t['ticker'] for t in open_trades]
    
    # First: Check existing trades for SL/TP hits
    actions = []
    for trade in open_trades:
        try:
            engine = StockEngine(trade['ticker'])
            hist = engine.get_market_data(period="5d", interval="1d")
            if hist is None or hist.empty:
                continue
            current_price = hist['Close'].iloc[-1]
            
            # Update current price
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE auto_trades SET current_price=? WHERE id=?", (current_price, trade['id']))
            conn.commit()
            conn.close()
            
            # Check stop loss
            if current_price <= trade['sl']:
                _close_trade(trade['id'], current_price, 'وقف خسارة')
                actions.append({'type': 'sl_hit', 'ticker': trade['ticker'], 'price': current_price})
            
            # Check take profit
            elif current_price >= trade['tp']:
                _close_trade(trade['id'], current_price, 'هدف ربح')
                actions.append({'type': 'tp_hit', 'ticker': trade['ticker'], 'price': current_price})
        except:
            continue
    
    # Second: Open new trades if slots available
    open_count = len(get_open_trades())  # Re-count after closing
    if open_count >= MAX_OPEN_TRADES:
        return {'action': 'full', 'message': f'المحفظة ممتلئة ({open_count}/{MAX_OPEN_TRADES})', 'actions': actions}
    
    # Scan stocks
    results = []
    for ticker in SCAN_TICKERS:
        if ticker in open_tickers:
            continue
        analysis = _analyze_stock(ticker)
        if analysis and analysis['score'] >= 65:
            results.append(analysis)
    
    results.sort(key=lambda x: x['score'], reverse=True)
    
    # Open trades for top opportunities
    new_trades = []
    capital = float(get_setting('current_capital', VIRTUAL_CAPITAL))
    slots = MAX_OPEN_TRADES - open_count
    
    for stock in results[:slots]:
        if not stock['levels'] or 'Entry' not in stock['levels']:
            continue
        
        entry = stock['price']
        sl = stock['levels'].get('SL', entry * 0.97)
        tp = stock['levels'].get('TP', entry * 1.06)
        
        # Position sizing: risk 2% of capital
        risk_amount = capital * RISK_PER_TRADE
        risk_per_share = abs(entry - sl)
        if risk_per_share <= 0:
            continue
        
        shares = int(risk_amount / risk_per_share)
        if shares <= 0:
            shares = 1
        
        position_cost = entry * shares
        if position_cost > capital * 0.3:  # Max 30% of capital per trade
            shares = int((capital * 0.3) / entry)
            if shares <= 0:
                continue
        
        trade_id = f"AT-{secrets.token_hex(4).upper()}"
        reason = " | ".join(stock['reasons'][:3])
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""INSERT INTO auto_trades 
            (id, ticker, entry_price, current_price, sl, tp, shares, entry_date, status, score, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (trade_id, stock['ticker'], entry, entry, sl, tp, shares, 
             datetime.now().strftime('%Y-%m-%d %H:%M'), stock['score'], reason))
        conn.commit()
        conn.close()
        
        new_trades.append({
            'id': trade_id,
            'ticker': stock['ticker'],
            'name': stock['name'],
            'entry': entry,
            'sl': sl,
            'tp': tp,
            'shares': shares,
            'score': stock['score'],
            'reason': reason,
        })
    
    return {
        'action': 'scanned',
        'new_trades': new_trades,
        'closed_actions': actions,
        'open_count': len(get_open_trades()),
    }


def _close_trade(trade_id, close_price, reason=''):
    """Closes a trade and updates capital."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM auto_trades WHERE id=?", (trade_id,))
    trade = dict(c.fetchone())
    
    pnl = (close_price - trade['entry_price']) * trade['shares']
    pnl_pct = ((close_price - trade['entry_price']) / trade['entry_price']) * 100
    
    c.execute("""UPDATE auto_trades 
        SET status='closed', current_price=?, close_date=?, pnl=?, pnl_pct=?, reason=?
        WHERE id=?""",
        (close_price, datetime.now().strftime('%Y-%m-%d %H:%M'), pnl, pnl_pct, 
         trade['reason'] + f' → {reason}', trade_id))
    
    # Update capital
    capital = float(get_setting('current_capital', VIRTUAL_CAPITAL))
    capital += pnl
    set_setting('current_capital', str(capital))
    
    conn.commit()
    conn.close()
    return pnl
