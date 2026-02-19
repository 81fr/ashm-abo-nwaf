import requests

# 1. Login
session = requests.Session()
login_url = "http://127.0.0.1:5000/login"
response = session.post(login_url, data={'username': 'admin', 'password': 'Az@123'})

if response.status_code == 200 and "dashboard" in response.url:
    print("Login Successful")
else:
    print("Login Failed")
    exit()

# 2. Test Chat
chat_url = "http://127.0.0.1:5000/api/chat"
payload = {"message": "تحليل فني لـ AAPL"}
response = session.post(chat_url, json=payload)

if response.status_code == 200:
    print("Chat Response:", response.json())
else:
    print("Chat Failed:", response.text)
