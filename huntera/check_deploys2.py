import requests, time

cred = open(r"C:\Users\danie\.config\opencode\credentials.env").read()
api_key = [l.split("=",1)[1].strip() for l in cred.splitlines() if l.startswith("RENDER_API_KEY=")][0]
h = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
sid = "srv-da6it8u7bikc738oeml0"

r = requests.get(f"https://api.render.com/v1/services/{sid}/deploys?limit=5", headers=h)
for d in r.json():
    dep = d["deploy"]
    print(f'{dep["id"]} | {dep["status"]} | {dep["createdAt"]}')
