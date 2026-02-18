import yfinance as yf
import pandas as pd
import numpy as np

class StockEngine:
    def __init__(self, ticker):
        self.ticker_symbol = ticker.upper()
        self.ticker = yf.Ticker(self.ticker_symbol)
        self.info = self.ticker.info
        
    def get_market_data(self, period="1y", interval="1d"):
        """Fetches historical market data."""
        history = self.ticker.history(period=period, interval=interval)
        return history

    def calculate_technical_indicators(self, df):
        """Calculates RSI, MACD, and EMA."""
        # EMA
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        return df

    def screen_shariah_compliance(self):
        """
        Screens for Shariah compliance based on common financial ratios.
        Criteria:
        1. Debt/MarketCap < 33%
        2. (Cash + Interest)/MarketCap < 33%
        3. Receivables/TotalAssets < 49%
        4. Sector Check (Prohibited: Banks, Alcohol, Gambling, etc.)
        """
        try:
            # 1. Sector Check
            prohibited_sectors = ["Banks", "Regional Banks", "Financial Services", "Insurance", "Tobacco", "Gambling", "Alcohol", "Adult Entertainment"]
            sector = self.info.get("sector", "")
            industry = self.info.get("industry", "")
            
            if sector in prohibited_sectors or industry in prohibited_sectors:
                return False, f"Non-Compliant Sector: {sector or industry}"

            # 2. Financial Ratios
            # Market Cap
            market_cap = self.info.get("marketCap")
            if not market_cap:
                return None, "Market Cap data missing"

            # Balance Sheet Data
            balance_sheet = self.ticker.quarterly_balance_sheet
            if balance_sheet.empty:
                return None, "Balance Sheet data missing"
            
            latest_bs = balance_sheet.iloc[:, 0] # Get most recent quarter
            
            # Total Debt
            total_debt = latest_bs.get("Total Debt", 0)
            debt_ratio = total_debt / market_cap
            
            # Cash & Interest Bearing Securities
            cash = latest_bs.get("Cash And Cash Equivalents", 0)
            st_investments = latest_bs.get("Short Term Investments", 0)
            cash_interest_ratio = (cash + st_investments) / market_cap
            
            # Accounts Receivable
            receivables = latest_bs.get("Net Receivables", 0)
            total_assets = latest_bs.get("Total Assets", 1) # Avoid division by zero
            receivables_ratio = receivables / total_assets
            
            # Pass/Fail
            reasons = []
            compliant = True
            
            if debt_ratio >= 0.33:
                compliant = False
                reasons.append(f"Debt/MarketCap: {debt_ratio:.2%} (Limit: 33%)")
            if cash_interest_ratio >= 0.33:
                compliant = False
                reasons.append(f"Cash+Interest/MarketCap: {cash_interest_ratio:.2%} (Limit: 33%)")
            if receivables_ratio >= 0.49:
                compliant = False
                reasons.append(f"Receivables/TotalAssets: {receivables_ratio:.2%} (Limit: 49%)")
                
            status_desc = "Compliant" if compliant else "Non-Compliant: " + ", ".join(reasons)
            return compliant, status_desc

        except Exception as e:
            return None, f"Error during screening: {str(e)}"

    def get_recommendation(self, df):
        """Simple rule-based recommendation based on technicals."""
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 0
        # RSI Check
        if latest['RSI'] < 30: score += 2 # Oversold
        elif latest['RSI'] > 70: score -= 2 # Overbought
        
        # MACD Cross
        if latest['MACD'] > latest['Signal_Line'] and prev['MACD'] <= prev['Signal_Line']:
            score += 2 # Bullish cross
        elif latest['MACD'] < latest['Signal_Line'] and prev['MACD'] >= prev['Signal_Line']:
            score -= 2 # Bearish cross
            
        # EMA Trend
        if latest['Close'] > latest['EMA50']: score += 1
        else: score -= 1
        
        if score >= 2: return "Buy (شراء)"
        if score <= -2: return "Sell (بيع)"
        return "Hold (انتظار/مراقبة)"

if __name__ == "__main__":
    # Test with a known stock
    engine = StockEngine("AAPL")
    hist = engine.get_market_data()
    hist = engine.calculate_technical_indicators(hist)
    is_halal, reason = engine.screen_shariah_compliance()
    rec = engine.get_recommendation(hist)
    
    print(f"Ticker: AAPL")
    print(f"Shariah Status: {reason}")
    print(f"Technical Recommendation: {rec}")
    print(f"Current Price: {hist['Close'].iloc[-1]:.2f}")
