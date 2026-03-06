import yfinance as yf
import pandas as pd
import numpy as np

class StockEngine:
    TICKER_MAP = {
        "SPX": "^GSPC",
        "NDX": "^NDX",
        "DJI": "^DJI",
        "VIX": "^VIX"
    }

    def __init__(self, ticker):
        self.original_ticker = ticker.upper()
        self.ticker_symbol = self.TICKER_MAP.get(self.original_ticker, self.original_ticker)
        self.ticker = yf.Ticker(self.ticker_symbol)
        
        try:
            self.info = self.ticker.info
        except:
            self.info = {}
        
        if not self.info:
            self.info = {}
            
        if "longName" not in self.info and "shortName" in self.info:
            self.info["longName"] = self.info["shortName"]
        
    def get_market_data(self, period="1y", interval="1d"):
        """Fetches historical market data."""
        try:
            history = self.ticker.history(period=period, interval=interval)
            return history
        except Exception as e:
            print(f"Error fetching data for {self.original_ticker}: {e}")
            return pd.DataFrame()

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
        
        # Support and Resistance (Reversal Zones)
        # Using a simple rolling window to find local minima and maxima
        window = 20
        df['Resistance'] = df['High'].rolling(window=window, center=False).max()
        df['Support'] = df['Low'].rolling(window=window, center=False).min()
        
        # Shift back slightly so today's extreme doesn't immediately become the line if it's new
        df['Resistance'] = df['Resistance'].shift(1)
        df['Support'] = df['Support'].shift(1)
        
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
                return False, f"قطاع غير متوافق: {sector or industry}"

            # 2. Financial Ratios
            # Market Cap
            market_cap = self.info.get("marketCap")
            if not market_cap:
                return None, "بيانات القيمة السوقية مفقودة"

            # Balance Sheet Data
            balance_sheet = self.ticker.quarterly_balance_sheet
            if balance_sheet.empty:
                return None, "بيانات الميزانية العمومية مفقودة"
            
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
                reasons.append(f"الديون/القيمة: {debt_ratio:.2%} (الحد: 33%)")
            if cash_interest_ratio >= 0.33:
                compliant = False
                reasons.append(f"الكاش/القيمة: {cash_interest_ratio:.2%} (الحد: 33%)")
            if receivables_ratio >= 0.49:
                compliant = False
                reasons.append(f"المستحقات/الأصول: {receivables_ratio:.2%} (الحد: 49%)")
                
            status_desc = "متوافق" if compliant else "غير متوافق: " + ", ".join(reasons)
            return compliant, status_desc

        except Exception as e:
            return None, f"خطأ أثناء الفحص الشرعي: {str(e)}"

    def calculate_atr(self, df, period=14):
        """Calculates Average True Range (ATR)."""
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        
        df['ATR'] = true_range.rolling(window=period).mean()
        return df

    def get_recommendation(self, df):
        """Standard recommendation with Entry, SL, and TP based on ATR."""
        df = self.calculate_atr(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 0
        # RSI Check
        if latest['RSI'] < 40: score += 1 # Undervalued / Approaching oversold
        elif latest['RSI'] > 70: score -= 2 # Overbought
        
        # MACD Trend and Cross
        if latest['MACD'] > latest['Signal_Line']:
            score += 1 # Bullish MACD Trend
            if prev['MACD'] <= prev['Signal_Line']:
                score += 1 # Bullish cross today
        elif latest['MACD'] < latest['Signal_Line']:
            score -= 1 # Bearish MACD Trend
            if prev['MACD'] >= prev['Signal_Line']:
                score -= 1 # Bearish cross today
            
        # EMA Trend
        if latest['Close'] > latest['EMA50']: score += 1
        else: score -= 1
        
        # Determine Signal and Levels
        signal = "Hold (انتظار/مراقبة)"
        levels = {}
        
        close_price = latest['Close']
        atr = latest['ATR'] if not pd.isna(latest['ATR']) else (close_price * 0.02) # Fallback if ATR is NaN
        
        support = latest['Support'] if 'Support' in latest and not pd.isna(latest['Support']) else close_price * 0.95
        resistance = latest['Resistance'] if 'Resistance' in latest and not pd.isna(latest['Resistance']) else close_price * 1.05
        
        if score >= 2:
            signal = "Buy (شراء)"
            levels = {
                "Entry": close_price,
                "SL": close_price - (2 * atr),
                "TP": close_price + (4 * atr)
            }
        elif score <= -2:
            signal = "Sell (بيع)"
            levels = {
                "Entry": close_price,
                "SL": close_price + (2 * atr),
                "TP": close_price - (4 * atr)
            }
            
        levels["Support"] = support
        levels["Resistance"] = resistance
            
        return signal, levels

    def scan_market(self, tickers=None):
        """Scans a list of tickers for Buy signals."""
        if tickers is None:
            # Minimal list for Vercel 10s Serverless limit
            tickers = ["AAPL", "MSFT", "NVDA", "TSLA", "META"]
            
        opportunities = []
        
        for ticker in tickers:
            try:
                # Create a temporary engine for each ticker
                temp_engine = StockEngine(ticker)
                hist = temp_engine.get_market_data(period="6mo")
                
                if len(hist) < 50: continue # Skip if not enough data
                
                hist = temp_engine.calculate_technical_indicators(hist)
                signal, levels = temp_engine.get_recommendation(hist)
                
                if "Buy" in signal:
                    opportunities.append({
                        "ticker": ticker,
                        "signal": signal,
                        "price": levels['Entry'],
                        "sl": levels['SL'],
                        "tp": levels['TP']
                    })
            except Exception as e:
                print(f"Error scanning {ticker}: {e}")
                continue
                
        return opportunities

    def get_options_data(self):
        """Fetches and summarizes options data for the nearest expiration."""
        try:
            expirations = self.ticker.options
            if not expirations:
                return None
                
            nearest_expiry = expirations[0]
            chain = self.ticker.option_chain(nearest_expiry)
            
            calls = chain.calls
            puts = chain.puts
            
            # Extract total volume and open interest
            call_vol = calls['volume'].sum() if not calls['volume'].empty else 0
            put_vol = puts['volume'].sum() if not puts['volume'].empty else 0
            call_oi = calls['openInterest'].sum() if not calls['openInterest'].empty else 0
            put_oi = puts['openInterest'].sum() if not puts['openInterest'].empty else 0
            
            # Put/Call Ratio
            pc_ratio_vol = put_vol / call_vol if call_vol > 0 else 0
            pc_ratio_oi = put_oi / call_oi if call_oi > 0 else 0
            
            return {
                "expirationDate": nearest_expiry,
                "callVolume": call_vol,
                "putVolume": put_vol,
                "callOpenInterest": call_oi,
                "putOpenInterest": put_oi,
                "putCallRatioVol": round(pc_ratio_vol, 2),
                "putCallRatioOI": round(pc_ratio_oi, 2)
            }
        except Exception as e:
            print(f"Error fetching options for {self.original_ticker}: {e}")
            return None

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
