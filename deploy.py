"""
PythonAnywhere Auto-Deploy Script
Usage: python deploy.py <API_TOKEN>

Get your token from: https://www.pythonanywhere.com/user/faisal511n1/account/#api_token
"""
import sys
import requests

USERNAME = "faisal511n1"
DOMAIN = f"{USERNAME}.pythonanywhere.com"
API_BASE = f"https://www.pythonanywhere.com/api/v0/user/{USERNAME}"

def deploy(token):
    headers = {"Authorization": f"Token {token}"}
    
    # Step 1: Create a new console to run git pull
    print("🔄 Step 1: Running git pull on server...")
    r = requests.post(f"{API_BASE}/consoles/", headers=headers, json={
        "executable": "bash",
        "arguments": "",
        "working_directory": f"/home/{USERNAME}/ashm-abo-nwaf"
    })
    
    if r.status_code == 201:
        console_id = r.json()['id']
        # Send git pull command
        requests.post(f"{API_BASE}/consoles/{console_id}/send_input/", headers=headers, json={
            "input": "cd ~/ashm-abo-nwaf && git pull origin main\n"
        })
        import time
        time.sleep(8)
        
        # Get output
        output_r = requests.get(f"{API_BASE}/consoles/{console_id}/get-latest-output/", headers=headers)
        if output_r.status_code == 200:
            print(output_r.json().get('output', 'No output'))
        
        # Kill the temp console
        requests.delete(f"{API_BASE}/consoles/{console_id}/", headers=headers)
        print("✅ Git pull completed!")
    else:
        print(f"❌ Console error: {r.status_code} - {r.text}")
        return
    
    # Step 2: Reload web app
    print("\n🔄 Step 2: Reloading web app...")
    r = requests.post(f"{API_BASE}/webapps/{DOMAIN}/reload/", headers=headers)
    if r.status_code == 200:
        print("✅ Web app reloaded successfully!")
        print(f"\n🌐 Your site is live at: https://{DOMAIN}")
    else:
        print(f"❌ Reload error: {r.status_code} - {r.text}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python deploy.py <YOUR_API_TOKEN>")
        print("Get your token from: https://www.pythonanywhere.com/user/faisal511n1/account/#api_token")
        sys.exit(1)
    
    deploy(sys.argv[1])
