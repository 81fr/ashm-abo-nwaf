import requests
import json
import time

s = requests.Session()
s.post("http://127.0.0.1:5000/login", data={"username": "admin", "password": "Az@123"})

print("Requesting AI insight for AAPL...")
start = time.time()
try:
    resp = s.post("http://127.0.0.1:5000/api/chat", json={"message": "رأي الذكاء في AAPL"}, timeout=60)
    print(f"Time detected: {time.time() - start:.2f}s")
    
    if resp.status_code == 200:
        data = resp.json()
        print("Response Snippet (AI Section):")
        text = data.get("response", "")
        # Extract plain text from AI section if possible, or just print the end
        if "رأي الذكاء الاصطناعي" in text:
            parts = text.split("رأي الذكاء الاصطناعي")
            print(parts[1][:500])
        else:
            print(text[:200])
    else:
        print("Error:", resp.status_code, resp.text)
except Exception as e:
    print("Request failed:", e)
