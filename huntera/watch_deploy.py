import requests, time

cred = open(r"C:\Users\danie\.config\opencode\credentials.env").read()
api_key = [l.split("=",1)[1].strip() for l in cred.splitlines() if l.startswith("RENDER_API_KEY=")][0]
h = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

did = "dep-da75nf7avr4c73b0ak0g"

for i in range(12):
    time.sleep(15)
    r = requests.get(f"https://api.render.com/v1/services/srv-da6it8u7bikc738oeml0/deploys?limit=1", headers=h)
    if r.status_code == 200:
        d = r.json()[0]["deploy"]
        print(f"[{(i+1)*15}s] {d['id']} | {d['status']}")
        if d["status"] in ("live", "build_failed", "update_failed", "deactivated"):
            break
