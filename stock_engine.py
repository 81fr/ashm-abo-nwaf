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
        
        # RSI (Wilder's Smoothing / EMA method — matches TradingView/Bloomberg)
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        # Support and Resistance (Reversal Zones)
        window = 20
        df['Resistance'] = df['High'].rolling(window=window, center=False).max().shift(1)
        df['Support'] = df['Low'].rolling(window=window, center=False).min().shift(1)

        # Bollinger Bands
        df['BB_Middle'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['BB_Middle'] + (df['BB_Std'] * 2)
        df['BB_Lower'] = df['BB_Middle'] - (df['BB_Std'] * 2)
        
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
            
            # Total Debt (handle NaN)
            total_debt = latest_bs.get("Total Debt", 0)
            if pd.isna(total_debt): total_debt = 0
            debt_ratio = total_debt / market_cap
            
            # Cash & Interest Bearing Securities (handle NaN)
            cash = latest_bs.get("Cash And Cash Equivalents", 0)
            if pd.isna(cash): cash = 0
            st_investments = latest_bs.get("Short Term Investments", 0)
            if pd.isna(st_investments): st_investments = 0
            cash_interest_ratio = (cash + st_investments) / market_cap
            
            # Accounts Receivable (handle NaN)
            receivables = latest_bs.get("Net Receivables", 0)
            if pd.isna(receivables): receivables = 0
            total_assets = latest_bs.get("Total Assets", 1)
            if pd.isna(total_assets) or total_assets == 0: total_assets = 1
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

    def scan_market(self, tickers=None, period="6mo", interval="1d"):
        """Scans a list of tickers for Buy signals using specific timeframe."""
        if tickers is None:
            # Minimal list for Vercel 10s Serverless limit
            tickers = ["AAPL", "MSFT", "NVDA", "TSLA", "META"]
            
        opportunities = []
        
        for ticker in tickers:
            try:
                # Create a temporary engine for each ticker
                temp_engine = StockEngine(ticker)
                hist = temp_engine.get_market_data(period=period, interval=interval)
                
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

    @staticmethod
    def get_global_sentiment():
        """Returns a simple market sentiment based on S&P 500 performance."""
        try:
            spy = yf.Ticker("^GSPC")
            data = spy.history(period="2d")
            if len(data) < 2:
                return "Neutral", 0
            
            last_close = data['Close'].iloc[-1]
            prev_close = data['Close'].iloc[-2]
            change_pct = ((last_close - prev_close) / prev_close) * 100
            
            if change_pct > 0.5:
                return "Bullish", change_pct
            elif change_pct < -0.5:
                return "Bearish", change_pct
            else:
                return "Neutral", change_pct
        except:
            return "Neutral", 0

    def calculate_fundamental_score(self):
        """Calculates a fundamental score (0-100) based on Value, Growth, and Quality."""
        score = 0
        try:
            # 1. Valuation (P/E Ratio)
            pe = self.info.get("trailingPE")
            if pe:
                if pe < 15: score += 25
                elif pe < 25: score += 15
                elif pe < 35: score += 5
            
            # 2. Profitability (ROE)
            roe = self.info.get("returnOnEquity")
            if roe:
                if roe > 0.20: score += 25
                elif roe > 0.10: score += 15
                elif roe > 0.05: score += 5
            
            # 3. Growth (Revenue Growth)
            growth = self.info.get("revenueGrowth")
            if growth:
                if growth > 0.20: score += 25
                elif growth > 0.10: score += 15
                elif growth > 0.05: score += 5
            
            # 4. Financial Health (Debt/Equity)
            de = self.info.get("debtToEquity")
            if de:
                if de < 50: score += 25
                elif de < 100: score += 15
                elif de < 150: score += 5
            
            # If data is missing for some fields, normalize the score
            return score
        except:
            return 50 # Default middle score if analysis fails

    def calculate_position_size(self, capital, risk_pct, entry, sl):
        """Calculates recommended shares and position size based on risk."""
        if entry == sl: return 0, 0
        
        risk_amount = capital * (risk_pct / 100)
        risk_per_share = abs(entry - sl)
        
        if risk_per_share == 0: return 0, 0
        
        shares = int(risk_amount / risk_per_share)
        pos_value = shares * entry
        
        return shares, pos_value

    @staticmethod
    def get_market_movers():
        """Fetches top gainers/losers from a sample of S&P 500."""
        tickers = ["AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOG", "AMD", "NFLX", "BRK-B", "JPM", "V", "UNH", "HD", "PG"]
        movers = []
        try:
            data = yf.download(tickers, period="1d", group_by='ticker', silent=True)
            for ticker in tickers:
                if ticker not in data: continue
                # Handle MultiIndex
                try:
                    ticker_data = data[ticker]
                    open_p = ticker_data['Open'].iloc[0]
                    close_p = ticker_data['Close'].iloc[0]
                    change = ((close_p - open_p) / open_p) * 100
                    movers.append({"ticker": ticker, "change": round(change, 2), "price": round(close_p, 2)})
                except:
                    continue
            
            # Sort by change
            movers.sort(key=lambda x: x['change'], reverse=True)
            return movers[:5], movers[-5:] # Top 5 Gainers, Top 5 Losers
        except Exception:
            return [], []

    # --- DATA CACHE ---
    _cache = {}
    _CACHE_TTL = 300  # 5 minutes

    def get_cached_data(self, period="6mo", interval="1d"):
        """Fetches market data with 5-minute in-memory cache."""
        import time as _time
        cache_key = (self.ticker_symbol, period, interval)
        now = _time.time()
        if cache_key in StockEngine._cache:
            ts, data = StockEngine._cache[cache_key]
            if now - ts < StockEngine._CACHE_TTL:
                return data.copy()
        data = self.get_market_data(period, interval)
        if data is not None and not data.empty:
            StockEngine._cache[cache_key] = (now, data)
        return data

    # --- VWAP ---
    def calculate_vwap(self, df):
        """Calculates Volume Weighted Average Price."""
        try:
            typical_price = (df['High'] + df['Low'] + df['Close']) / 3
            df['VWAP'] = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()
        except Exception:
            df['VWAP'] = df['Close']
        return df

    # --- CANDLESTICK PATTERNS ---
    def detect_candlestick_patterns(self, df):
        """Detects Japanese candlestick patterns from the last 3 candles."""
        patterns = []
        if df is None or len(df) < 3:
            return patterns
        try:
            c = df.iloc[-1]  # Current candle
            p = df.iloc[-2]  # Previous candle
            pp = df.iloc[-3] # Two candles ago

            body = abs(c['Close'] - c['Open'])
            upper_shadow = c['High'] - max(c['Close'], c['Open'])
            lower_shadow = min(c['Close'], c['Open']) - c['Low']
            candle_range = c['High'] - c['Low']

            # Doji: body is very small relative to range
            if candle_range > 0 and body / candle_range < 0.1:
                patterns.append("دوجي (Doji) - تردد في السوق")

            # Hammer: long lower shadow, small body at top
            if body > 0 and lower_shadow > 2 * body and upper_shadow < body * 0.5:
                patterns.append("مطرقة (Hammer) - إشارة انعكاس صعودي")

            # Shooting Star: long upper shadow, small body at bottom
            if body > 0 and upper_shadow > 2 * body and lower_shadow < body * 0.5:
                patterns.append("نجمة ساقطة (Shooting Star) - إشارة انعكاس هبوطي")

            # Bullish Engulfing
            p_body = abs(p['Close'] - p['Open'])
            if (p['Close'] < p['Open'] and  # Previous was red
                c['Close'] > c['Open'] and   # Current is green
                c['Open'] <= p['Close'] and c['Close'] >= p['Open'] and
                body > p_body):
                patterns.append("ابتلاع صعودي (Bullish Engulfing) - قوة شرائية")

            # Bearish Engulfing
            if (p['Close'] > p['Open'] and  # Previous was green
                c['Close'] < c['Open'] and   # Current is red
                c['Open'] >= p['Close'] and c['Close'] <= p['Open'] and
                body > p_body):
                patterns.append("ابتلاع هبوطي (Bearish Engulfing) - ضغط بيعي")

            # Morning Star (3-candle bullish reversal)
            pp_body = abs(pp['Close'] - pp['Open'])
            if (pp['Close'] < pp['Open'] and  # First: red
                p_body < pp_body * 0.3 and     # Second: small body (star)
                c['Close'] > c['Open'] and     # Third: green
                c['Close'] > (pp['Open'] + pp['Close']) / 2):
                patterns.append("نجمة الصباح (Morning Star) - انعكاس صعودي قوي")

        except Exception:
            pass
        return patterns

    # --- FIBONACCI RETRACEMENT ---
    def calculate_fibonacci_levels(self, df, period=60):
        """Calculates Fibonacci retracement levels from recent high/low."""
        try:
            recent = df.tail(period)
            high = recent['High'].max()
            low = recent['Low'].min()
            diff = high - low

            levels = {
                '0.0%': high,
                '23.6%': high - 0.236 * diff,
                '38.2%': high - 0.382 * diff,
                '50.0%': high - 0.5 * diff,
                '61.8%': high - 0.618 * diff,
                '78.6%': high - 0.786 * diff,
                '100.0%': low
            }
            return levels
        except Exception:
            return {}

    # --- BACKTESTING ENGINE ---
    def backtest_strategy(self, df, strategy='ema_cross'):
        """Backtests EMA crossover strategy on historical data."""
        try:
            if df is None or len(df) < 60:
                return {"error": "Insufficient data for backtesting"}

            trades = []
            position = None

            for i in range(1, len(df)):
                ema20 = df['EMA20'].iloc[i]
                ema50 = df['EMA50'].iloc[i]
                prev_ema20 = df['EMA20'].iloc[i-1]
                prev_ema50 = df['EMA50'].iloc[i-1]
                price = df['Close'].iloc[i]

                # Buy signal: EMA20 crosses above EMA50
                if prev_ema20 <= prev_ema50 and ema20 > ema50 and position is None:
                    position = {'entry': price, 'entry_idx': i}

                # Sell signal: EMA20 crosses below EMA50
                elif prev_ema20 >= prev_ema50 and ema20 < ema50 and position is not None:
                    pnl_pct = ((price - position['entry']) / position['entry']) * 100
                    trades.append({
                        'entry': round(float(position['entry']), 2),
                        'exit': round(float(price), 2),
                        'pnl_pct': round(float(pnl_pct), 2),
                        'win': pnl_pct > 0
                    })
                    position = None

            if not trades:
                return {"total_trades": 0, "message": "No trades generated"}

            wins = [t for t in trades if t['win']]
            losses = [t for t in trades if not t['win']]

            # Calculate max drawdown
            cumulative = 0
            peak = 0
            max_dd = 0
            for t in trades:
                cumulative += t['pnl_pct']
                if cumulative > peak:
                    peak = cumulative
                dd = peak - cumulative
                if dd > max_dd:
                    max_dd = dd

            total_return = sum(t['pnl_pct'] for t in trades)

            return {
                "total_trades": len(trades),
                "winning_trades": len(wins),
                "losing_trades": len(losses),
                "win_rate": round(len(wins) / len(trades) * 100, 1),
                "total_return_pct": round(float(total_return), 2),
                "avg_win": round(sum(t['pnl_pct'] for t in wins) / len(wins), 2) if wins else 0,
                "avg_loss": round(sum(t['pnl_pct'] for t in losses) / len(losses), 2) if losses else 0,
                "max_drawdown_pct": round(float(max_dd), 2),
                "trades": trades[-10:]  # Last 10 trades
            }
        except Exception as e:
            return {"error": str(e)}

    # --- PORTFOLIO ANALYTICS ---
    @staticmethod
    def calculate_portfolio_metrics(trades):
        """Calculates portfolio-level metrics from closed trades."""
        try:
            if not trades:
                return {"error": "No trades to analyze"}

            returns = []
            for t in trades:
                entry = float(t.get('entry_price', 0))
                close = float(t.get('close_price', entry))
                shares = int(t.get('shares', 1))
                if entry > 0:
                    pnl = (close - entry) * shares
                    pnl_pct = ((close - entry) / entry) * 100
                    returns.append({'pnl': pnl, 'pnl_pct': pnl_pct})

            if not returns:
                return {"error": "No valid trades"}

            total_pnl = sum(r['pnl'] for r in returns)
            pcts = [r['pnl_pct'] for r in returns]
            wins = [r for r in returns if r['pnl'] > 0]
            losses = [r for r in returns if r['pnl'] <= 0]

            avg_return = np.mean(pcts)
            std_return = np.std(pcts) if len(pcts) > 1 else 1
            sharpe = round(float(avg_return / std_return), 2) if std_return > 0 else 0

            # Max drawdown
            cumulative = 0
            peak = 0
            max_dd = 0
            for r in returns:
                cumulative += r['pnl_pct']
                if cumulative > peak:
                    peak = cumulative
                dd = peak - cumulative
                if dd > max_dd:
                    max_dd = dd

            return {
                "total_pnl": round(float(total_pnl), 2),
                "total_trades": len(returns),
                "win_rate": round(len(wins) / len(returns) * 100, 1),
                "avg_win": round(float(np.mean([r['pnl'] for r in wins])), 2) if wins else 0,
                "avg_loss": round(float(np.mean([r['pnl'] for r in losses])), 2) if losses else 0,
                "sharpe_ratio": sharpe,
                "max_drawdown_pct": round(float(max_dd), 2)
            }
        except Exception as e:
            return {"error": str(e)}

if __name__ == "__main__":
    engine = StockEngine("AAPL")
    hist = engine.get_market_data()
    hist = engine.calculate_technical_indicators(hist)
    hist = engine.calculate_vwap(hist)
    print(f"Ticker: AAPL")
    print(f"VWAP: {hist['VWAP'].iloc[-1]:.2f}")
    print(f"Patterns: {engine.detect_candlestick_patterns(hist)}")
    print(f"Fibonacci: {engine.calculate_fibonacci_levels(hist)}")
    print(f"Backtest: {engine.backtest_strategy(hist)}")
