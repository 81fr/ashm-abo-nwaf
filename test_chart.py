import requests
import json
import time

s = requests.Session()
# Login
s.post("http://127.0.0.1:5000/login", data={"username": "admin", "password": "Az@123"})
time.sleep(1)

# Chat Request for Technical Analysis
resp = s.post("http://127.0.0.1:5000/api/chat", json={"message": "تحليل فني AAPL"})

if resp.status_code == 200:
    data = resp.json()
    if data.get("chart"):
        print("Chart JSON received successfully.")
        print("Chart Data Length:", len(data["chart"]))
    else:
        print("Chart JSON MISSING.")
    print("Response Text:", data.get("response", "No Response"))
else:
    print("Request Failed:", resp.text)
