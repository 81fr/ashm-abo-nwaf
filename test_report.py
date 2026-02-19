import requests
import json
import time

s = requests.Session()
# Login
s.post("http://127.0.0.1:5000/login", data={"username": "admin", "password": "Az@123"})
time.sleep(1)

# Chat Request for Full Report (just ticker)
print("Sending Full Report Request for TSLA...")
resp = s.post("http://127.0.0.1:5000/api/chat", json={"message": "TSLA"})

if resp.status_code == 200:
    data = resp.json()
    response_text = data.get("response", "No Response")
    print("Response Length:", len(response_text))
    
    # Check for key components
    keywords = ["P/E", "RSI", "MACD", "الوضع الشرعي", "رأي الذكاء الاصطناعي", "أهداف الصفقة"]
    for kw in keywords:
        if kw in response_text:
            print(f"✅ Found: {kw}")
        else:
            print(f"❌ Missing: {kw}")
            
    if data.get("chart"):
        print("✅ Chart Data Present")
    else:
        print("❌ Chart Data Missing")
        
    print("\n--- Response ---\n")
    print(response_text[:500] + "...")
else:
    print("Request Failed:", resp.text)
