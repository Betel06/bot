import requests, json

cred = open(r"C:\Users\danie\.config\opencode\credentials.env").read()
api_key = [l.split("=",1)[1].strip() for l in cred.splitlines() if l.startswith("RENDER_API_KEY=")][0]
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}
service_id = "srv-da6it8u7bikc738oeml0"

# Voltar build command simples (sem Playwright)
body = {
    "serviceDetails": {
        "runtime": "python",
        "envSpecificDetails": {
            "buildCommand": "pip install flask requests",
            "startCommand": "python huntera/monitor_huntera.py"
        }
    }
}

print("Removendo Playwright do build...")
r = requests.patch(f"https://api.render.com/v1/services/{service_id}", headers=headers, json=body)
print(f"Update: {r.status_code}")

# Deploy
print("Deployando...")
r = requests.post(f"https://api.render.com/v1/services/{service_id}/deploys", headers=headers, json={})
print(f"Deploy: {r.status_code} - {r.text[:200]}")
