import requests
import json
import time

s = requests.Session()
# Login
s.post("http://127.0.0.1:5000/login", data={"username": "admin", "password": "Az@123"})
time.sleep(1)

# Chat Request for Market Scan
print("Sending Market Scan Request (this may take 5-10 seconds)...")
resp = s.post("http://127.0.0.1:5000/api/chat", json={"message": "عطني سهم"})

if resp.status_code == 200:
    data = resp.json()
    print("Response Text:", data.get("response", "No Response"))
else:
    print("Request Failed:", resp.text)
