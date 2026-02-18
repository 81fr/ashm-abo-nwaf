import os
from openai import OpenAI

class AIAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        else:
            self.client = None

    def get_ai_insight(self, ticker, info, technical_data, shariah_status):
        """Generates a qualitative analysis using LLM."""
        if not self.client:
            return "ملاحظة: مفتاح OpenAI API غير متوفر. يرجى إضافته للحصول على تحليلات ذكاء اصطناعي تفصيلية. حالياً يتم عرض التحليل الفني فقط."

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
        
        Please provide a detailed investment recommendation in Arabic. 
        Focus on:
        1. Business fundamentals.
        2. Impact of Shariah compliance on long-term holding.
        3. Risk factors.
        4. Final verdict (Buy/Sell/Hold).
        Keep it professional and concise.
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "أنت خبير مالي في سوق الأسهم الأمريكي ومتخصص في الاستثمار المتوافق مع الشريعة الإسلامية."},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error generating AI insight: {str(e)}"

if __name__ == "__main__":
    # Internal test (Expected to fail if no API key, which is fine)
    analyzer = AIAnalyzer()
    print(analyzer.get_ai_insight("AAPL", {"sector": "Tech"}, None, "Compliant"))
