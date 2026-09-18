import requests, time

cred = open(r"C:\Users\danie\.config\opencode\credentials.env").read()
api_key = [l.split("=",1)[1].strip() for l in cred.splitlines() if l.startswith("RENDER_API_KEY=")][0]
auth_headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
sid = "srv-da6it8u7bikc738oeml0"

r = requests.post(f"https://api.render.com/v1/services/{sid}/deploys", headers=auth_headers, json={})
print("Deploy:", r.status_code)
did = r.json().get("id", "")
print("ID:", did)

time.sleep(30)

r2 = requests.get(f"https://api.render.com/v1/deploys/{did}", headers=auth_headers)
print("Status:", r2.status_code)
if r2.status_code == 200:
    d = r2.json()
    print("Deploy status:", d.get("status"))
    print("Trigger:", d.get("trigger"))

time.sleep(90)

r3 = requests.get(f"https://api.render.com/v1/deploys/{did}", headers=auth_headers)
if r3.status_code == 200:
    d = r3.json()
    print("Final status:", d.get("status"))
