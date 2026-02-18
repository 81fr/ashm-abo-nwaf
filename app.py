import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from stock_engine import StockEngine
from ai_analyzer import AIAnalyzer
import os

# Page Config
st.set_page_config(
    page_title="US Stock Bot | بوت تحليل الأسهم",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Look
st.markdown("""
    <style>
    .main {
        background-color: #f5f7f9;
        font-family: 'Inter', sans-serif;
    }
    .stMetric {
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .complaint-card {
        padding: 20px;
        border-radius: 10px;
        color: white;
        font-weight: bold;
        text-align: center;
        margin-bottom: 20px;
    }
    .halal {
        background-color: #28a745;
    }
    .haram {
        background-color: #dc3545;
    }
    .warning {
        background-color: #ffc107;
        color: black;
    }
    .recommendation-card {
        padding: 20px;
        border-radius: 10px;
        background-color: #ffffff;
        border-left: 5px solid #00a59b;
        margin-top: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.title("🏦 US Stock Bot")
    st.markdown("تحليل ذكي وتوافق شرعي")
    ticker_input = st.text_input("أدخل رمز السهم (e.g. AAPL, TSLA, NVDA):", value="AAPL").upper()
    api_key = st.text_input("مفتاح OpenAI API (اختياري):", type="password")
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
    
    st.divider()
    st.info("""
    **المعايير الشرعية المستخدمة:**
    - الديون < 33% 
    - الكاش والفوائد < 33%
    - المستحقات < 49%
    - القطاع نشاط حلال
    """)

# Main Content
if ticker_input:
    try:
        with st.spinner(f"جاري تحليل {ticker_input}..."):
            engine = StockEngine(ticker_input)
            analyzer = AIAnalyzer(api_key if api_key else None)
            
            # Data Fetching
            hist = engine.get_market_data()
            hist = engine.calculate_technical_indicators(hist)
            is_halal, shariah_reason = engine.screen_shariah_compliance()
            recommendation = engine.get_recommendation(hist)
            
            # Header
            col1, col2 = st.columns([3, 1])
            with col1:
                st.title(f"{engine.info.get('longName', ticker_input)} ({ticker_input})")
                st.subheader(f"Price: ${hist['Close'].iloc[-1]:.2f}")
            
            with col2:
                if is_halal is True:
                    st.markdown(f'<div class="complaint-card halal">متوافق مع الشريعة ✅</div>', unsafe_allow_html=True)
                elif is_halal is False:
                    st.markdown(f'<div class="complaint-card haram">غير متوافق شرعاً ❌</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="complaint-card warning">تعذر جلب البيانات الشرعية ⚠️</div>', unsafe_allow_html=True)

            # Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Recommendation", recommendation)
            m2.metric("RSI (14)", f"{hist['RSI'].iloc[-1]:.2f}")
            m3.metric("52W High", f"${engine.info.get('fiftyTwoWeekHigh', 0):.2f}")
            m4.metric("Market Cap", f"${engine.info.get('marketCap', 0)/1e9:.1f}B")

            # Chart
            st.subheader("الرسم البياني وتوجه السهم")
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=hist.index,
                            open=hist['Open'], high=hist['High'],
                            low=hist['Low'], close=hist['Close'], name='Price'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA20'], name='EMA 20', line=dict(color='orange', width=1)))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA50'], name='EMA 50', line=dict(color='blue', width=1)))
            fig.update_layout(template="plotly_white", xaxis_rangeslider_visible=False, height=500)
            st.plotly_chart(fig, use_container_width=True)

            # Shariah Details & AI Insight
            tab1, tab2 = st.tabs(["📊 تفاصيل الحالة الشرعية", "🤖 تحليل الذكاء الاصطناعي"])
            
            with tab1:
                st.write(f"**النتيجة:** {shariah_reason}")
                # Show ratios if available
                if is_halal is not None:
                    # In a real app, we'd calculate and show precise values here
                    st.info("تم الفحص بناءً على آخر تقرير مالي ربعي متاح.")
            
            with tab2:
                insight = analyzer.get_ai_insight(ticker_input, engine.info, hist, shariah_reason)
                st.markdown(f'<div class="recommendation-card">{insight}</div>', unsafe_allow_html=True)

    except Exception as e:
        st.error(f"حدث خطأ أثناء جلب البيانات: {str(e)}")
        st.info("تأكد من صحة رمز السهم أو حاول مرة أخرى لاحقاً.")

else:
    st.write("يرجى إدخال رمز السهم في الشريط الجانبي للبدء.")
