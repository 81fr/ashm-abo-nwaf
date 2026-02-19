from flask import Flask, render_template, request, redirect, url_for, session
import os
import secrets
import sys

# Add parent directory to path to import StockEngine and AIAnalyzer
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from stock_engine import StockEngine
from ai_analyzer import AIAnalyzer
import json
import plotly
import plotly.graph_objects as go

app = Flask(__name__)
# Generate a random secret key for session management
app.secret_key = secrets.token_hex(16)

# Hardcoded credentials for demonstration
# In production, use a database or environment variables
USERNAME = "admin"
PASSWORD = "Az@123"
DEFAULT_API_KEY = "AIzaSyCWPlKqiET1w46PSJ8WbRgGYwGIQczwrgM"

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] == USERNAME and request.form['password'] == PASSWORD:
            session['username'] = request.form['username']
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid credentials. Please try again.'
    return render_template('login.html', error=error)

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
        session['openai_api_key'] = api_key
        return {"status": "success", "message": "API Key saved for this session."}
    return {"error": "No key provided"}, 400

@app.route('/api/chat', methods=['POST'])
def chat():
    if 'username' not in session:
        return {"error": "Unauthorized"}, 401
    
    data = request.json
    user_message = data.get('message', '')
    
    # 1. Extract Ticker
    import re
    # Keywords to ignore (common technical terms that might look like tickers)
    IGNORED_KEYWORDS = ['LSTM', 'BERT', 'AI', 'MACD', 'RSI', 'EMA', 'SMA', 'ATR']
    
    ticker_match = re.search(r'\b[A-Z]{2,5}\b', user_message)
    potential_ticker = ticker_match.group(0) if ticker_match else None
    
    ticker = None
    if potential_ticker and potential_ticker not in IGNORED_KEYWORDS:
        ticker = potential_ticker
    
    if not ticker and 'last_ticker' in session:
        ticker = session['last_ticker']
    elif not ticker:
         # If no ticker found and no last ticker, we can't proceed with stock analysis
         # unless it's a general greeting or scanner request.
         pass 

    if ticker:
        session['last_ticker'] = ticker
    
    response = ""
    
    try:
        # Determine intent that doesn't require specific ticker first
        if "عطني سهم" in user_message or "توصيات" in user_message or "فرص" in user_message or "سهم" in user_message:
             # Scanner logic handled below
             pass
        elif "مرحبا" in user_message or "هلا" in user_message:
             # Greeting handled below
             pass
        elif not ticker:
             return {"response": "الرجاء تحديد اسم السهم (مثل TSLA أو AAPL) للبدء في التحليل."}

        # Initialize Engine if we have a ticker or if we are scanning (scanner creates its own engines)
        if ticker:
            engine = StockEngine(ticker)
            hist = engine.get_market_data()
            
            if hist.empty:
                 return {"response": f"❌ عذراً، لم أتمكن من جلب بيانات للسهم **{ticker}**. يرجى التأكد من الرمز والمحاولة مرة أخرى."}
                 
        # Determine intent
        if "تحليل أساسي" in user_message or "البيانات المالية" in user_message:
            is_halal, reason = engine.screen_shariah_compliance()
            response = f"""
            📊 **التحليل الأساسي لـ {ticker}:**
            
            - **القطاع:** {engine.info.get('sector', 'N/A')}
            - **الصناعة:** {engine.info.get('industry', 'N/A')}
            - **القيمة السوقية:** ${engine.info.get('marketCap', 0)/1e9:.2f} مليار
            - **مكرر الربحية (P/E):** {engine.info.get('trailingPE', 'N/A')}
            
            **الوضع الشرعي:** {reason} {'✅' if is_halal else '❌'}
            """
            
        elif "تحليل فني" in user_message or "المؤشرات الفنية" in user_message:
            hist = engine.get_market_data()
            hist = engine.calculate_technical_indicators(hist)
            rec_signal, levels = engine.get_recommendation(hist)
            latest = hist.iloc[-1]
            
            # Generate Plotly Chart
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=hist.index,
                            open=hist['Open'], high=hist['High'],
                            low=hist['Low'], close=hist['Close'], name='Price'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA20'], name='EMA 20', line=dict(color='orange', width=1)))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA50'], name='EMA 50', line=dict(color='blue', width=1)))
            
            # Add Trade Levels to Chart if available
            if levels:
                fig.add_hline(y=levels['TP'], line_dash="dash", line_color="green", annotation_text="TP", annotation_position="top right")
                fig.add_hline(y=levels['SL'], line_dash="dash", line_color="red", annotation_text="SL", annotation_position="bottom right")
                fig.add_hline(y=levels['Entry'], line_dash="dot", line_color="white", annotation_text="Entry")

            fig.update_layout(
                title=f'{ticker} Analysis',
                yaxis_title='Price',
                template="plotly_dark",
                height=400,
                margin=dict(l=20, r=20, t=40, b=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='white')
            )
            
            chart_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
            
            # Format Trade Levels for Text Response
            trade_details = ""
            if levels:
                trade_details = f"""
                <div style="margin-top: 10px; text-align: right; background: #333; padding: 10px; border-radius: 5px;">
                    🎯 **أهداف الصفقة:**<br>
                    🟢 **هدف الربح (TP):** ${levels['TP']:.2f}<br>
                    🔴 **وقف الخسارة (SL):** ${levels['SL']:.2f}<br>
                    🔵 **سعر الدخول:** ${levels['Entry']:.2f}
                </div>
                """
            
            rec_class = 'buy' if 'شراء' in rec_signal else 'sell' if 'بيع' in rec_signal else 'hold'
            
            response = (
                f"📈 **التحليل الفني لـ {ticker}:**\n\n"
                f"- **السعر الحالي:** ${latest['Close']:.2f}\n"
                f"- **RSI (14):** {latest['RSI']:.2f}\n"
                f"- **MACD:** {latest['MACD']:.3f}\n\n"
                f"{trade_details}\n\n"
                f'<div class="recommendation-box {rec_class}">{rec_signal}</div>'
            )
            
            return {"response": response, "chart": chart_json}
            
        elif "توقع" in user_message or "ذكاء" in user_message or "مستشار" in user_message or "رأيك" in user_message:
             # AI Analysis
            hist = engine.get_market_data()
            hist = engine.calculate_technical_indicators(hist)
            is_halal, reason = engine.screen_shariah_compliance()
            
            # Use the AI Analyzer with session key
            api_key = session.get('openai_api_key') or DEFAULT_API_KEY
            analyzer = AIAnalyzer(api_key=api_key) 
            response = analyzer.get_ai_insight(ticker, engine.info, hist, reason)
            
        elif "عطني سهم" in user_message or "توصيات" in user_message or "فرص" in user_message or "سهم" in user_message:
            opportunities = engine.scan_market()
            
            if not opportunities:
                response = "🔍 قمت بفحص أهم الأسهم التقنية ولم أجد فرص **شراء** واضحة حالياً بناءً على المؤشرات الفنية. السوق قد يكون في حالة تذبذب أو هبوط."
            else:
                response = "🚀 **الفرص المتاحة حالياً (إشارة شراء):**\n\n"
                for opp in opportunities:
                    response += f"🔹 **{opp['ticker']}** بسعر ${opp['price']:.2f}\n"
                    response += f"   🎯 هدف: ${opp['tp']:.2f} | 🛑 وقف: ${opp['sl']:.2f}\n"
                    response += f"-----------------------------------\n"
                
                response += "\n⚠️ *هذه ليست نصيحة مالية، بل تحليل فني آلي.*"

        elif "مرحبا" in user_message or "هلا" in user_message:
             response = f"مرحباً بك يا {session['username']}! أنا جاهز لتحليل الأسواق. جرب أن تسألني عن 'تحليل فني لـ TSLA' أو 'رأي الذكاء الاصطناعي في AAPL'."
             
        else:
             # Default to Full Report if only ticker is mentioned (or no specific intent detected)
            hist = engine.get_market_data()
            hist = engine.calculate_technical_indicators(hist)
            rec_signal, levels = engine.get_recommendation(hist)
            latest = hist.iloc[-1]
            is_halal, compliance_reason = engine.screen_shariah_compliance()
            
            # 1. AI Analysis
            api_key = session.get('openai_api_key') or DEFAULT_API_KEY
            analyzer = AIAnalyzer(api_key=api_key) 
            ai_insight = analyzer.get_ai_insight(ticker, engine.info, hist, compliance_reason)
            
            # 2. Charts
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=hist.index,
                            open=hist['Open'], high=hist['High'],
                            low=hist['Low'], close=hist['Close'], name='Price'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA20'], name='EMA 20', line=dict(color='orange', width=1)))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA50'], name='EMA 50', line=dict(color='blue', width=1)))
            
            if levels:
                fig.add_hline(y=levels['TP'], line_dash="dash", line_color="green", annotation_text="TP", annotation_position="top right")
                fig.add_hline(y=levels['SL'], line_dash="dash", line_color="red", annotation_text="SL", annotation_position="bottom right")
                fig.add_hline(y=levels['Entry'], line_dash="dot", line_color="white", annotation_text="Entry")

            fig.update_layout(
                title=f'{ticker} Analysis',
                yaxis_title='Price',
                template="plotly_dark",
                height=400,
                margin=dict(l=20, r=20, t=40, b=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='white')
            )
            chart_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
            
            # 3. Trade Levels Formatting
            trade_details = ""
            if levels:
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
        response = f"حدث خطأ أثناء تحليل {ticker}: {str(e)}"

    return {"response": response}

if __name__ == '__main__':
    # Using host='0.0.0.0' to make it accessible externally if needed
    # Using debug=True for development
    app.run(debug=True, host='0.0.0.0', port=5000)
