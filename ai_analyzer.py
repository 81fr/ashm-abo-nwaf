import os
from openai import OpenAI
from datetime import datetime

BEGINNER_SUMMARY_HTML = """
<div style="background: linear-gradient(135deg, #1a1a1a, #0a0a0a); border: 1px solid rgba(212, 175, 55, 0.3); border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); font-family: 'Cairo', sans-serif;" dir="rtl">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
        <h3 style="color: #fff; margin: 0; font-size: 1.2rem;"><i class="fas fa-brain" style="color: #d4af37;"></i> ملخص المستشار للمبتدئين</h3>
        <span style="background: rgba(212, 175, 55, 0.1); color: #d4af37; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; border: 1px solid rgba(212, 175, 55, 0.2);">{ticker}</span>
    </div>
    
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
        <div style="background: rgba(255,255,255,0.03); padding: 12px; border-radius: 10px; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
            <div style="color: #888; font-size: 0.8rem; margin-bottom: 5px;">القرار النهائي</div>
            <div style="font-size: 1.1rem; font-weight: 800; color: {verdict_color};">{verdict_text}</div>
        </div>
        <div style="background: rgba(255,255,255,0.03); padding: 12px; border-radius: 10px; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
            <div style="color: #888; font-size: 0.8rem; margin-bottom: 5px;">مستوى المخاطرة</div>
            <div style="font-size: 1.1rem; font-weight: 800; color: {risk_color};">{risk_text}</div>
        </div>
    </div>
    
    <div style="background: rgba(212, 175, 55, 0.05); border-right: 4px solid #d4af37; padding: 12px; border-radius: 4px 10px 10px 4px; color: #eee; line-height: 1.6; font-size: 0.95rem;">
        <strong>💡 الخلاصة:</strong> {simple_reason}
    </div>
</div>
"""

UNIFIED_TABLE_HTML = """
<table style="width: 100%; border-collapse: collapse; background-color: #111; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.3); text-align: right; border: 1px solid #333;" dir="rtl">
    <thead>
        <tr style="background: linear-gradient(135deg, #d4af37, #aa8529); color: #000;">
            <th colspan="2" style="padding: 12px; font-size: 1.1rem; text-align: center;"><i class="fas fa-list-ul"></i> البيانات التفصيلية: {ticker}</th>
        </tr>
    </thead>
    <tbody>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; width: 45%; color: #d4af37; background: rgba(212,175,55,0.02);">الشركة والقطاع</td>
            <td style="padding: 12px; color: #fff;">(Company & Sector)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">السعر الحالي</td>
            <td style="padding: 12px; color: #fff; font-weight: bold;">{current_price}</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">الإشارة الذكية</td>
            <td style="padding: 12px; font-weight: bold;">(Buy/Sell Signal)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">سعر الدخول (أفضل سعر)</td>
            <td style="padding: 12px; color: #3498db; font-weight: bold;">(Entry Price)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">الهدف (سعر البيع)</td>
            <td style="padding: 12px; color: #2ecc71; font-weight: bold;">(Take Profit)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">وقف الخسارة (حماية)</td>
            <td style="padding: 12px; color: #ff4d4d; font-weight: bold;">(Stop Loss)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">الربح المتوقع</td>
            <td style="padding: 12px; color: #fff;">(Expected Profit %)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">مدة الاحتفاظ (أقصى وقت)</td>
            <td style="padding: 12px; color: #f1c40f; font-weight: bold;">(Max Hold Time)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">إدارة المخاطر (لـ $10k)</td>
            <td style="padding: 12px; color: #f1c40f; font-weight: bold;">(Position Size Recommendation)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">قوة الأساسيات (0-100)</td>
            <td style="padding: 12px; color: #fff; font-weight: bold;">(Fundamental Score)</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">مناطق الدعم والمقاومة</td>
            <td style="padding: 12px; color: #ccc; font-size: 0.9rem;">{support} - {resistance}</td>
        </tr>
        <tr style="border-bottom: 1px solid #222;">
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">الوضع الشرعي</td>
            <td style="padding: 12px;">(Shariah Status)</td>
        </tr>
        <tr>
            <td style="padding: 12px; font-weight: bold; color: #d4af37; background: rgba(212,175,55,0.02);">نصيحة للمبتدئين</td>
            <td style="padding: 12px; color: #aaa; font-style: italic; font-size: 0.85rem;">(Pro Tip)</td>
        </tr>
        <tr>
            <td colspan="2" style="padding: 15px; text-align: center; background: rgba(255,255,255,0.02);">
                <button onclick="saveToPortfolio('{ticker_only}')" class="btn-primary" style="background: var(--primary-gold); color: #000; border: none; padding: 10px 20px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: all 0.3s;">
                    <i class="fas fa-plus-circle"></i> حفظ الصفقة في محفظتي (تجريبي)
                </button>
            </td>
        </tr>
    </tbody>
</table>
"""

UNIFIED_TABLE_HTML_EN = """
<table style="width: 100%; border-collapse: collapse; margin-top: 15px; background-color: #222; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.3); text-align: left;" dir="ltr">
    <thead>
        <tr style="background: linear-gradient(135deg, #d4af37, #aa8529); color: #000;">
            <th colspan="2" style="padding: 10px; font-size: 1.05rem; text-align: center;">🎯 Comprehensive Analysis: {ticker}</th>
        </tr>
    </thead>
    <tbody>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; width: 40%; color: #d4af37;">Company / Sector</td>
            <td style="padding: 10px;">(Company & Sector)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Current Price</td>
            <td style="padding: 10px;">{current_price}</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Signal (Buy/Sell)</td>
            <td style="padding: 10px; font-weight: bold; color: #fff;">(Buy/Sell Signal)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Entry Price</td>
            <td style="padding: 10px; color: #3498db; font-weight: bold;">(Entry/Limit Price)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Target Price (TP)</td>
            <td style="padding: 10px; color: #2ecc71; font-weight: bold;">(Take Profit - TP Price)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Stop Loss (SL)</td>
            <td style="padding: 10px; color: #ff4d4d; font-weight: bold;">(Stop Loss Price)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Expected Profit (%)</td>
            <td style="padding: 10px; font-weight: bold;">(Expected Profit %)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Support Level</td>
            <td style="padding: 10px; color: #3498db; font-weight: bold;">{support}</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Resistance Level</td>
            <td style="padding: 10px; color: #e74c3c; font-weight: bold;">{resistance}</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Risk/Reward (R/R)</td>
            <td style="padding: 10px;">(Risk % / Reward-to-Risk)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Suggested Entry Time</td>
            <td style="padding: 10px;">(Suggested Entry Time)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Suggested Exit Time</td>
            <td style="padding: 10px;">(Suggested Exit Time / Max Hold)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Strike (Options Only)</td>
            <td style="padding: 10px;">(Option Strike or 'N/A')</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Strategic Recommendations</td>
            <td style="padding: 10px;">(Strategic Suggestions / Best Practices)</td>
        </tr>
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Fundamentals & Purification</td>
            <td style="padding: 10px; color: #f39c12;">(Fundamentals & Purification)</td>
        </tr>
        <tr>
            <td style="padding: 10px; font-weight: bold; color: #d4af37;">Analysis Time</td>
            <td style="padding: 10px;">{generation_time}</td>
        </tr>
    </tbody>
</table>
"""

class AIAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.provider = "groq"
        self.client = None

        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.groq.com/openai/v1"
            )

    def get_ai_insight(self, ticker, info, technical_data, shariah_status, tf_title="يومي", timeframe_val="1d", lang="ar"):
        """Generates a qualitative analysis using Open-Source Llama 3 via Groq."""
        if not self.api_key:
             return "Note: Groq API Key missing." if lang == "en" else "ملاحظة: مفتاح Groq API غير متوفر."

        current_price = technical_data['Close'].iloc[-1] if technical_data is not None and not technical_data.empty else 0
        rsi = technical_data['RSI'].iloc[-1] if technical_data is not None and not technical_data.empty else 0
        macd = technical_data['MACD'].iloc[-1] if technical_data is not None and not technical_data.empty else 0
        support = technical_data['Low'].rolling(window=20).min().iloc[-1] if technical_data is not None and not technical_data.empty else 0
        resistance = technical_data['High'].rolling(window=20).max().iloc[-1] if technical_data is not None and not technical_data.empty else 0

        # Enforce highly strict max hold times
        hold_time_rules = {
            "15m": ("15 to 45 minutes", "15 إلى 45 دقيقة"),
            "30m": ("30 to 90 minutes", "30 إلى 90 دقيقة"),
            "1h": ("1 to 3 hours", "ساعة إلى 3 ساعات"),
            "1d": ("1 to 5 days", "يوم إلى 5 أيام"),
            "1mo": ("1 to 6 months", "شهر إلى 6 أشهر")
        }
        hold_en, hold_ar = hold_time_rules.get(timeframe_val, ("based on your strategy", "معتمد على استراتيجيتك"))
        hold_instruction = f"MUST BE '{hold_en}'" if lang == "en" else f"يجب أن يكون '{hold_ar}'"

        table_template = UNIFIED_TABLE_HTML_EN if lang == "en" else UNIFIED_TABLE_HTML
        table_html = table_template.format(
            ticker=f"{ticker} ({tf_title})",
            current_price=f"${current_price:.2f}",
            support=f"${support:.2f}",
            resistance=f"${resistance:.2f}",
            ticker_only=ticker,
            generation_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        prompt_en = f"""
        Analyze the US stock {ticker} ({info.get('longName', ticker)}) on the {tf_title} timeframe.
        Current Price: ${current_price:.2f}
        RSI: {rsi:.2f}, MACD: {macd:.2f}
        Shariah Status: {shariah_status}

        You are a top-tier financial advisor for beginners. 
        CRITICAL: For 'Suggested Exit Time / Max Hold', it {hold_instruction}.
        
        You MUST return TWO parts in your response:
        1. The BEGINNER_SUMMARY_HTML populated with:
           - verdict_text: (Strong Buy, Buy, Wait, or Avoid)
           - verdict_color: (#2ecc71 for buy, #f1c40f for wait, #e74c3c for avoid)
           - risk_text: (Low, Moderate, or High)
           - risk_color: (#2ecc71 for low, #f1c40f for moderate, #e74c3c for high)
           - simple_reason: A one-sentence simple explanation for a beginner.
        2. The Detailed HTML Table filled with data.
        
        BEGINNER_SUMMARY_HTML Template:
        {BEGINNER_SUMMARY_HTML}
        
        Detailed Table Template:
        {table_html}
        """

        prompt_ar = f"""
        حلل السهم الأمريكي {ticker} ({info.get('longName', ticker)}) على الإطار الزمني {tf_title}.
        السعر الحالي: ${current_price:.2f}
        RSI: {rsi:.2f}, MACD: {macd:.2f}
        الوضع الشرعي: {shariah_status}

        أنت مستشار مالي خبير يوجه المبتدئين. 
        تنبيه هام: للحقل 'وقت الخروج المقترح (أقصى مدة)'، {hold_instruction}.
        
        يجب أن تعيد جزئين في ردك:
        1. قالب BEGINNER_SUMMARY_HTML مملوءاً بالقيم التالية:
           - verdict_text: (شراء قوي، شراء، انتظار، أو تجنب)
           - verdict_color: (#2ecc71 للشراء، #f1c40f للانتظار، #e74c3c للتجنب)
           - risk_text: (منخفضة، متوسطة، أو عالية)
           - risk_color: (#2ecc71 لمنخفضة، #f1c40f لمتوسطة، #e74c3c لعالية)
           - simple_reason: جملة واحدة بسيطة تشرح السبب لمبتدئ لا يفهم في الأسهم.
        2. جدول البيانات التفصيلي HTML مملوءاً بالبيانات، مع ذكر 'قوة الأساسيات (0-100)' و 'إدارة المخاطر (لـ $10k)' بشكل دقيق.
        
        قالب الملخص للمبتدئين:
        {BEGINNER_SUMMARY_HTML}
        
        قالب الجدول التفصيلي:
        {table_html}
        """

        prompt = prompt_en if lang == "en" else prompt_ar

        try:
            if self.client:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": f"You are a master financial advisor who simplifies complex data for beginners. Return ONLY the two HTML blocks (Summary and Table)."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000
                )
                return response.choices[0].message.content
            return "Error: Groq client not initialized." if lang == "en" else "خطأ: لم يتم تهيئة الاتصال بـ Groq."
        except Exception as e:
            return f"Error: {str(e)}" if lang == "en" else f"خطأ في توليد التحليل: {str(e)}"

    def get_opportunities_insight(self, opportunities_list, tf_title="يومي", timeframe_val="1d"):
        """Generates an AI-driven report for a list of market opportunities."""
        if not self.api_key:
             return None
             
        # Enforce highly strict max hold times to prevent LLM hallucinating days for a 15-minute chart
        hold_time_rules = {
            "15m": "MUST BE '15 إلى 45 دقيقة'",
            "30m": "MUST BE '30 إلى 90 دقيقة'",
            "1h": "MUST BE 'ساعة إلى 3 ساعات'",
            "1d": "MUST BE 'يوم إلى 5 أيام'",
            "1mo": "MUST BE 'شهر إلى 6 أشهر'"
        }
        hold_instruction = hold_time_rules.get(timeframe_val, "MUST BE 'معتمد على استراتيجيتك'")

        opps_text = "\n".join([
            f"- {opp['ticker']}: Buy at ${opp['price']:.2f}, Target ${opp['tp']:.2f}, Stop Loss ${opp['sl']:.2f}" 
            for opp in opportunities_list
        ])

        table_template = UNIFIED_TABLE_HTML.replace('{ticker}', f'[رمز السهم] ({tf_title})').replace('{current_price}', '[السعر]').replace('{support}', '[دعم]').replace('{resistance}', '[مقاومة]').replace('{ticker_only}', '[رمز_السهم]').replace('{generation_time}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        prompt = f"""
        I have scanned the market on the {tf_title} timeframe and found the following Technical Buy opportunities:
        {opps_text}

        Please act as an expert financial advisor. Provide a concise, highly professional summary in **Arabic** for these opportunities. 
        CRITICAL: For the 'Suggested Exit Time / Max Hold' (وقت الخروج المقترح (أقصى مدة)) field in the table for EVERY stock, it {hold_instruction}. You MUST NOT suggest a longer holding period than this under any circumstances! Do not invent any other duration.
        
        You MUST return ONLY the following HTML table format exactly as shown for EACH stock. Create a separate identical table for each stock and separate them with a `<br>` tag. Do not add conversational text.
        Fill irrelevant fields with 'غير مطبق للأسهم'.

        {table_template}
        """

        try:
            if self.client:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "أنت مستشار مالي خبير. تعطي إجابات دقيقة واحترافية باللغة العربية داخل القالب المطلوب فقط."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000
                )
                return response.choices[0].message.content
            return None
        except:
            return None

    def get_options_insight(self, ticker, current_price, options_data, technical_data=None, tf_title="يومي"):
        """Generates an AI-driven report analyzing options activity for a stock."""
        if not self.api_key or not options_data:
            return "بيانات الخيارات غير متوفرة أو أن مفتاح الذكاء الاصطناعي مفقود."

        support_val = "(غير متوفر)"
        res_val = "(غير متوفر)"
        
        if technical_data is not None and not technical_data.empty:
            support_val = f"${technical_data['Low'].rolling(window=20).min().iloc[-1]:.2f}"
            res_val = f"${technical_data['High'].rolling(window=20).max().iloc[-1]:.2f}"

        prompt = f"""
        Analyze the options chain activity for {ticker} dynamically considering the timeframe context ({tf_title}).
        Current Stock Price: ${current_price:.2f}
        Nearest Expiration Date: {options_data['expirationDate']}
        
        Options Activity Summary:
        - Call Volume: {int(options_data['callVolume']):,}
        - Put Volume: {int(options_data['putVolume']):,}
        - Call Open Interest: {int(options_data['callOpenInterest']):,}
        - Put Open Interest: {int(options_data['putOpenInterest']):,}
        - Put/Call Ratio (Volume): {options_data['putCallRatioVol']:.2f}
        - Put/Call Ratio (Open Interest): {options_data['putCallRatioOI']:.2f}

        Please act as an expert options trader. Provide a concise analysis strictly in **Arabic**.
        You MUST provide Expected Profit (الربح المتوقع), Risk Percentage (نسبة المخاطرة), Entry Price, Take Profit, Stop Loss, Entry Time, Exit Time, and Strategic Suggestions (المقترحات الاستراتيجية).
        CRITICAL: Keep your expected hold times and exit times realistic for the {tf_title} timeframe.
        You MUST return ONLY the following HTML table format exactly as shown, filled with data in Arabic. Do not add conversational text outside the table.
        Replace irrelevant fields with 'يعتمد على نظرة المتداول'.

        {UNIFIED_TABLE_HTML.format(ticker=f"{ticker} ({tf_title})", current_price=f"${current_price:.2f}", support=support_val, resistance=res_val, ticker_only=ticker, generation_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}
        """

        try:
            if self.client:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "أنت خبير محترف في تداول عقود الخيارات (Options) وتعطي تحليلات دقيقة بالعربية باستخدام الجدول."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000
                )
                return response.choices[0].message.content
            return "خطأ: لم يتم تهيئة الاتصال بـ Groq."
        except Exception as e:
            return f"خطأ في تحليل الخيارات: {str(e)}"

    def get_options_trade_signal(self, ticker, current_price, options_data, technical_data, tf_title="يومي", timeframe_val="1d"):
        """Generates a structured trading signal card for an options contract."""
        if not self.api_key:
            return "ملاحظة: مفتاح Groq API غير متوفر لتوليد إشارة التداول."

        rsi = technical_data['RSI'].iloc[-1] if technical_data is not None and not technical_data.empty else 0
        macd = technical_data['MACD'].iloc[-1] if technical_data is not None and not technical_data.empty else 0
        support = technical_data['Low'].rolling(window=20).min().iloc[-1] if technical_data is not None and not technical_data.empty else 0
        resistance = technical_data['High'].rolling(window=20).max().iloc[-1] if technical_data is not None and not technical_data.empty else 0
        expiration = options_data['expirationDate'] if options_data else "غير محدد"
        pc_ratio = options_data.get('putCallRatioVol', 0) if options_data else 0
        call_vol = options_data.get('callVolume', 0) if options_data else 0
        put_vol = options_data.get('putVolume', 0) if options_data else 0

        # Enforce highly strict max hold times to prevent LLM hallucinating days for a 15-minute chart
        hold_time_rules = {
            "15m": "MUST BE '15 إلى 45 دقيقة'",
            "30m": "MUST BE '30 إلى 90 دقيقة'",
            "1h": "MUST BE 'ساعة إلى 3 ساعات'",
            "1d": "MUST BE 'يوم إلى 5 أيام'",
            "1mo": "MUST BE 'شهر إلى 6 أشهر'"
        }
        hold_instruction = hold_time_rules.get(timeframe_val, "MUST BE 'معتمد على استراتيجيتك'")

        prompt = f"""
        Generate a highly specific, structured Options Trading Signal for {ticker} dynamically considering the timeframe context ({tf_title}).
        Current Stock Price: ${current_price:.2f}
        RSI (14): {rsi:.2f}
        MACD: {macd:.2f}
        Key Support Zone: ${support:.2f}
        Key Resistance Zone: ${resistance:.2f}
        Nearest Expiration Date: {expiration}
        Put/Call Ratio (Volume): {pc_ratio:.2f}
        Call Volume: {call_vol}
        Put Volume: {put_vol}
        
        CRITICAL: For the 'Suggested Exit Time / Max Hold' (وقت الخروج المقترح (أقصى مدة)) field in the table, it {hold_instruction}. You are severely penalized if you output days/weeks for an intraday interval!
        
        Based on the current momentum (RSI/MACD), the key zones, and options flow (Call/Put volume and P/C ratio), decide whether to recommend a CALL or a PUT option.
        Then, estimate a reasonable Strike Price near the money, a Limit Order price (سعر الدخول), a Stop Loss (SL), and a Take Profit (TP).
        Explicitly calculate the Expected Profit (الربح المتوقع) and Risk Percentage (نسبة المخاطرة).
        Provide clear Strategic Suggestions (المقترحات الاستراتيجية) and explicit Entry/Exit Times.
        Estimate a Purification Percentage (نسبة التطهير) or indicate 'الرجوع للقوائم الشرعية'.
        
        You MUST return ONLY the following HTML table format exactly as shown, filled with data in Arabic. Do not add conversational text outside this table. Use the exact inline CSS provided.
        
        {UNIFIED_TABLE_HTML.format(ticker=f"{ticker} ({tf_title})", current_price=f"${current_price:.2f}", support=f"${support:.2f}", resistance=f"${resistance:.2f}", ticker_only=ticker, generation_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}
        """

        try:
            if self.client:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "أنت خبير محترف في تداول عقود الأوبشن للأسهم الأمريكية. تعطي توصيات مباشرة وصارمة بناءً على القالب الموحد باللغة العربية."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000
                )
                return response.choices[0].message.content
            return "خطأ: لم يتم تهيئة الاتصال بـ Groq."
        except Exception as e:
            return f"خطأ في توليد التوصية: {str(e)}"
    def get_market_briefing(self, market_data):
        """Generates a professional AI morning briefing for the US market."""
        if not self.api_key:
            return "مفتاح Groq API غير متوفر."

        prompt = f"""
        Generate a professional US Market Morning Briefing in Arabic for a beginner audience.
        Analyze the following data:
        - S&P 500: {market_data.get('spx_change', 0):.2f}% change
        - Nasdaq 100: {market_data.get('ndx_change', 0):.2f}% change
        - Dow Jones: {market_data.get('dji_change', 0):.2f}% change
        - Market Sentiment: {market_data.get('sentiment', 'Neutral')}
        
        The briefing should include:
        1. 🌤️ ملخص الجلسة السابقة (Previous Session Summary)
        2. 🧭 الاتجاه المتوقع اليوم (Expected Trend)
        3. 💡 نصيحة الخبير للمبتدئين (Consultant's Tip)
        
        Keep it concise, professional, and encouraging. Use Arabic only. 
        Format it in HTML with nice styles for a dashboard popup.
        """
        
        try:
            if self.client:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "أنت مستشار مالي خبير تقدم ملخصاً يومياً لسوق الأسهم الأمريكي بالعربي للمبتدئين."},
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.choices[0].message.content
        except Exception as e:
            return f"خطأ في توليد الملخص: {str(e)}"
        return "تعذر الحصول على الملخص حالياً."
