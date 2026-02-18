from stock_engine import StockEngine

def test_haram_stock():
    # JPM is a bank, should be non-compliant by sector
    engine = StockEngine("JPM")
    is_halal, reason = engine.screen_shariah_compliance()
    print(f"Ticker: JPM")
    print(f"Shariah Compliance: {is_halal}")
    print(f"Reason: {reason}")
    
    if is_halal is False and "Sector" in reason:
        print("VERIFICATION SUCCESS: JPM correctly identified as Non-Compliant due to sector.")
    else:
        print("VERIFICATION FAILURE: JPM logic incorrect.")

if __name__ == "__main__":
    test_haram_stock()
