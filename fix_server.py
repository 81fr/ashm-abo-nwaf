import requests, time

API_BASE = 'https://www.pythonanywhere.com/api/v0/user/faisal511n1'
headers = {'Authorization': 'Token 071926537b8c5d5c4d4607e9bae863971246c37e'}

# Kill existing consoles
consoles = requests.get(f'{API_BASE}/consoles/', headers=headers).json()
for c in consoles:
    requests.delete(f'{API_BASE}/consoles/{c["id"]}/', headers=headers)
time.sleep(2)

# Create console
r = requests.post(f'{API_BASE}/consoles/', headers=headers, json={'executable': 'bash', 'working_directory': '/home/faisal511n1/ashm-abo-nwaf'})
cid = r.json()['id']
time.sleep(3)

# Send git reset hard command
requests.post(f'{API_BASE}/consoles/{cid}/send_input/', headers=headers, json={'input': 'git fetch origin main\ngit reset --hard origin/main\n'})
time.sleep(10)

# Get output
output = requests.get(f'{API_BASE}/consoles/{cid}/get_latest_output/', headers=headers).json().get('output', '')
print("GIT OUTPUT:\n", output)

# Reload webapp
requests.post(f'{API_BASE}/webapps/faisal511n1.pythonanywhere.com/reload/', headers=headers)
print("Reloaded!")

# Clean up
requests.delete(f'{API_BASE}/consoles/{cid}/', headers=headers)
