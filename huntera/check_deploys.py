import requests
cred = open(r"C:\Users\danie\.config\opencode\credentials.env").read()
api_key = [l.split("=",1)[1].strip() for l in cred.splitlines() if l.startswith("RENDER_API_KEY=")][0]
headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
r = requests.get("https://api.render.com/v1/services/srv-da6it8u7bikc738oeml0/deploys?limit=5", headers=headers)
for d in r.json():
    dep = d["deploy"]
    did = dep["id"]
    status = dep["status"]
    msg = dep["commit"]["message"][:60]
    print(f"{did} | {status} | {msg}")
