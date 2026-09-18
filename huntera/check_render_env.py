import requests

credPath = r"C:\Users\danie\.config\opencode\credentials.env"
api_key = ""
with open(credPath) as f:
    for line in f:
        if line.startswith("RENDER_API_KEY="):
            api_key = line.split("=",1)[1].strip()

headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
service_id = "srv-da6it8u7bikc738oeml0"

resp = requests.get(f"https://api.render.com/v1/services/{service_id}/env-vars", headers=headers)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    envs = resp.json()
    for e in envs:
        key = e.get("key", "")
        val = e.get("value", "")
        if "TELEGRAM" in key or "HUNTERA" in key:
            print(f"  {key} = {val[:20]}...")
else:
    print(resp.text[:300])
