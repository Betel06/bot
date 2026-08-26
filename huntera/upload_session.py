import json
import os
import requests

cred_path = r"C:\Users\danie\.config\opencode\credentials.env"
api_key = ""
with open(cred_path) as f:
    for line in f:
        if line.startswith("RENDER_API_KEY="):
            api_key = line.split("=", 1)[1].strip()

service_id = "srv-da6it8u7bikc738oeml0"

session_path = r"C:\Users\danie\Documents\BOT\huntera\huntera_session.json"
with open(session_path, "r", encoding="utf-8") as f:
    content = f.read()

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

# Formato correto: PUT /services/{id}/secret-files/{filename}
url = f"https://api.render.com/v1/services/{service_id}/secret-files/huntera_session.json"
body = {"content": content}

print(f"Enviando ({len(content)} chars)...")
resp = requests.put(url, headers=headers, json=body)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")
