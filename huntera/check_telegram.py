import requests, json

cred = open(r"C:\Users\danie\.config\opencode\credentials.env").read()
token = [l.split("=",1)[1].strip() for l in cred.splitlines() if l.startswith("TELEGRAM_TOKEN=")][0]

# Check env vars on Render
credPath = r"C:\Users\danie\.config\opencode\credentials.env"
api_key = ""
chat_id_local = ""
token_local = ""
with open(credPath) as f:
    for line in f:
        if line.startswith("RENDER_API_KEY="):
            api_key = line.split("=",1)[1].strip()
        if line.startswith("TELEGRAM_CHAT_ID="):
            chat_id_local = line.split("=",1)[1].strip()
        if line.startswith("TELEGRAM_TOKEN="):
            token_local = line.split("=",1)[1].strip()

print(f"Local CHAT_ID: {chat_id_local}")
print(f"Local TOKEN: {token_local[:15]}...")

# Check Render env vars
headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
service_id = "srv-da6it8u7bikc738oeml0"
resp = requests.get(f"https://api.render.com/v1/services/{service_id}/env-vars", headers=headers)
if resp.status_code == 200:
    envs = resp.json()
    for e in envs:
        if "TELEGRAM" in e.get("key", ""):
            val = e.get("value", "")
            print(f"Render {e['key']}: {val[:15]}...")
else:
    print(f"Erro ao listar env vars: {resp.status_code}")

# Test send
url = f"https://api.telegram.org/bot{token}/getMe"
r = requests.get(url)
print(f"Bot info: {r.json().get('result', {}).get('username', 'ERRO')}")
