import os
from openai import OpenAI
import google.generativeai as genai

class AIAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.provider = "groq"
        self.client = None

        if self.api_key:
            # We use the OpenAI SDK since Groq provides an OpenAI-compatible API
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.groq.com/openai/v1"
            )

    def get_ai_insight(self, ticker, info, technical_data, shariah_status):
        """Generates a qualitative analysis using Open-Source Llama 3 via Groq."""
        if not self.api_key:
             return "ملاحظة: مفتاح Groq API غير متوفر. يرجى إضافته للحصول على تحليلات ذكاء اصطناعي تفصيلية باستخدام Llama 3."

        prompt = f"""
        Analyze the US stock {ticker} ({info.get('longName', ticker)}).
        Financial Profile:
        - Sector: {info.get('sector')}
        - Revenue Growth: {info.get('revenueGrowth')}
        - Forward P/E: {info.get('forwardPE')}
        - Shariah Status: {shariah_status}
        
        Technical Indicators:
        - Current Price: {technical_data['Close'].iloc[-1]:.2f}
        - RSI: {technical_data['RSI'].iloc[-1]:.2f}
        - MACD: {technical_data['MACD'].iloc[-1]:.2f}
        
        Please provide a detailed investment recommendation **strictly in Arabic**. 
        Focus on:
        1. Business fundamentals.
        2. Impact of Shariah compliance on long-term holding.
        3. Risk factors.
        4. Final verdict (Buy/Sell/Hold).
        
        **Important:** The entire response must be in Arabic. Do not use English unless necessary for technical terms (which should be explained in Arabic).
        Keep it professional and concise.
        """

        try:
            if self.client:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "أنت خبير مالي احترافي في سوق الأسهم وتقوم بتقديم نصائح تعتمد على البيانات المتوفرة والتحليل الفني والأساسي متوافق مع الشريعة."},
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.choices[0].message.content
            else:
                return "خطأ: لم يتم تهيئة الاتصال بـ Groq."

        except Exception as e:
            return f"خطأ في توليد تحليل الذكاء الاصطناعي ({self.provider}): {str(e)}"

    def get_opportunities_insight(self, opportunities_list):
        """Generates an AI-driven report for a list of market opportunities."""
        if not self.api_key:
             return None # Fallback to default text if no AI

        # Format opportunities for the prompt
        opps_text = "\n".join([
            f"- {opp['ticker']}: Buy at ${opp['price']:.2f}, Target ${opp['tp']:.2f}, Stop Loss ${opp['sl']:.2f}" 
            for opp in opportunities_list
        ])

        prompt = f"""
        I have scanned the market and found the following Technical Buy opportunities based on indicator crossovers and ATR levels:
        {opps_text}

        Please act as an expert financial advisor. Provide a concise, highly professional summary in **Arabic** for these opportunities. 
        For each stock:
        1. Mention briefly why it's a good company fundamentally or what its sector is.
        2. State the entry price, target price, and stop loss.
        3. Calculate and state the Risk/Reward ratio (نسبة المخاطرة للعائد).
        4. Provide a final brief advice on portfolio sizing or risk management for these trades.

        Keep the formatting clean using markdown. **The response must be strictly in Arabic.**
        """

        try:
            if self.client:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "أنت مستشار مالي خبير. تعطي إجابات دقيقة واحترافية باللغة العربية."},
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.choices[0].message.content
            return None
        except:
            return None

if __name__ == "__main__":
    # Internal test (Expected to fail if no API key, which is fine)
    analyzer = AIAnalyzer()
    print(analyzer.get_ai_insight("AAPL", {"sector": "Tech"}, None, "Compliant"))
