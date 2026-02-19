import requests
import json
import time

s = requests.Session()
# Login
s.post("http://127.0.0.1:5000/login", data={"username": "admin", "password": "Az@123"})
time.sleep(1)

# 1. Test "LSTM" (Should NOT crash, should ask for ticker or use previous)
print("--- Testing 'LSTM' input ---")
resp = s.post("http://127.0.0.1:5000/api/chat", json={"message": "توقعات LSTM"})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json().get('response')}")

# 2. Test Invalid Ticker "XYZ123" (Should return error message)
print("\n--- Testing Invalid Ticker 'XYZ123' ---")
resp = s.post("http://127.0.0.1:5000/api/chat", json={"message": "تحليل XYZ123"})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json().get('response')}")

# 3. Test Valid Ticker "AAPL" (Should work)
print("\n--- Testing Valid Ticker 'AAPL' ---")
resp = s.post("http://127.0.0.1:5000/api/chat", json={"message": "تحليل AAPL"})
print(f"Status: {resp.status_code}")
print(f"Response Length: {len(resp.json().get('response'))}")
