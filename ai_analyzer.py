import os
from openai import OpenAI
import google.generativeai as genai

class AIAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.provider = None
        self.client = None
        self.model = None

        if self.api_key:
            if self.api_key.startswith("sk-"):
                self.provider = "openai"
                self.client = OpenAI(api_key=self.api_key)
            elif self.api_key.startswith("AIza"):
                self.provider = "google"
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-flash-latest')
            else:
                # Fallback / assumption
                self.provider = "openai"
                self.client = OpenAI(api_key=self.api_key)

    def get_ai_insight(self, ticker, info, technical_data, shariah_status):
        """Generates a qualitative analysis using LLM (OpenAI or Gemini)."""
        if not self.api_key:
             return "ملاحظة: مفتاح API غير متوفر (OpenAI أو Gemini). يرجى إضافته للحصول على تحليلات ذكاء اصطناعي تفصيلية."

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
            if self.provider == "openai":
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "أنت خبير مالي في سوق الأسهم الأمريكي ومتخصص في الاستثمار المتوافق مع الشريعة الإسلامية."},
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.choices[0].message.content
            
            elif self.provider == "google":
                response = self.model.generate_content(prompt)
                return response.text
                
            else:
                return "Unknown AI provider configuration."

        except Exception as e:
            return f"Error generating AI insight ({self.provider}): {str(e)}"

if __name__ == "__main__":
    # Internal test (Expected to fail if no API key, which is fine)
    analyzer = AIAnalyzer()
    print(analyzer.get_ai_insight("AAPL", {"sector": "Tech"}, None, "Compliant"))
