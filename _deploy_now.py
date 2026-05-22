import requests, time

USERNAME = 'faisal511n1'
API_BASE = f'https://www.pythonanywhere.com/api/v0/user/{USERNAME}'
DOMAIN = f'{USERNAME}.pythonanywhere.com'
token = '071926537b8c5d5c4d4607e9bae863971246c37e'
headers = {'Authorization': f'Token {token}'}

# List existing consoles
r = requests.get(f'{API_BASE}/consoles/', headers=headers)
consoles = r.json()
print(f'Active consoles: {len(consoles)}')

# Kill all to free slots
for c in consoles:
    cid = c['id']
    print(f'Killing console {cid}...')
    requests.delete(f'{API_BASE}/consoles/{cid}/', headers=headers)

time.sleep(2)

# Create new console
print('Creating console for git pull...')
r = requests.post(f'{API_BASE}/consoles/', headers=headers, json={
    'executable': 'bash',
    'arguments': '',
    'working_directory': f'/home/{USERNAME}/ashm-abo-nwaf'
})
print(f'Create status: {r.status_code}')

if r.status_code == 201:
    console_id = r.json()['id']
    time.sleep(3)
    
    # Send git pull
    requests.post(f'{API_BASE}/consoles/{console_id}/send_input/', headers=headers, json={
        'input': 'cd ~/ashm-abo-nwaf && git pull origin main && echo DEPLOY_SUCCESS\n'
    })
    time.sleep(15)
    
    # Get output
    output_r = requests.get(f'{API_BASE}/consoles/{console_id}/get-latest-output/', headers=headers)
    if output_r.status_code == 200:
        out = output_r.json().get('output', '')
        for line in out.split('\n'):
            stripped = line.strip()
            if stripped:
                print(stripped)
    
    # Cleanup console
    requests.delete(f'{API_BASE}/consoles/{console_id}/', headers=headers)
else:
    print(f'Console error: {r.text[:300]}')

# Reload webapp
print('\nReloading webapp...')
rr = requests.post(f'{API_BASE}/webapps/{DOMAIN}/reload/', headers=headers)
print(f'Reload status: {rr.status_code}')
if rr.status_code == 200:
    print(f'Site live at: https://{DOMAIN}')
