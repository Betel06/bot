import requests, time

cred = open(r"C:\Users\danie\.config\opencode\credentials.env").read()
api_key = [l.split("=",1)[1].strip() for l in cred.splitlines() if l.startswith("RENDER_API_KEY=")][0]
h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}
owner_id = "tea-da3gfj2jnfac73cflfag"
old_sid = "srv-da6it8u7bikc738oeml0"

# 1. Delete old service
print("1. Deletando servico antigo...")
r = requests.delete(f"https://api.render.com/v1/services/{old_sid}", headers=h)
print(f"   Delete: {r.status_code}")

time.sleep(10)

# 2. Create new service
print("2. Criando novo servico...")
body = {
    "name": "bot-huntera",
    "ownerId": owner_id,
    "type": "web_service",
    "repo": "https://github.com/Betel06/bot",
    "branch": "main",
    "serviceDetails": {
        "runtime": "python",
        "envSpecificDetails": {
            "buildCommand": "pip install flask requests",
            "startCommand": "python huntera/monitor_huntera.py"
        },
        "ipAllowList": [{"cidrBlock": "0.0.0.0/0", "description": "everywhere"}]
    }
}
r = requests.post("https://api.render.com/v1/services", headers=h, json=body)
print(f"   Create: {r.status_code}")
if r.status_code in (200, 201):
    svc = r.json()
    new_sid = svc["id"]
    new_url = svc.get("url", "")
    print(f"   ID: {new_sid}")
    print(f"   URL: {new_url}")
else:
    print(f"   Erro: {r.text[:300]}")
    exit(1)

# 3. Set env vars
envs = {
    "TELEGRAM_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "HUNTERA_BOLSA_SLOTES": "20",
    "HUNTERA_SYSTEM_SELECAO_AUTO": "true",
    "HUNTERA_LIMITE_RISCO": "3",
    "HUNTERA_BANCO_INICIAL": "5000",
    "HUNTERA_ENTRADA_GP": "1000",
    "HUNTERA_ITEMS_POR_TIPO_LIMITE": "10",
    "HUNTERA_TEMPO_VENDA": "3"
}

# Read real values from credentials
for line in open(r"C:\Users\danie\.config\opencode\credentials.env"):
    if line.startswith("TELEGRAM_TOKEN="):
        envs["TELEGRAM_TOKEN"] = line.split("=",1)[1].strip()
    if line.startswith("TELEGRAM_CHAT_ID="):
        envs["TELEGRAM_CHAT_ID"] = line.split("=",1)[1].strip()

print("3. Configurando env vars...")
for k, v in envs.items():
    r = requests.post(f"https://api.render.com/v1/services/{new_sid}/env-vars", headers=h, json={"key": k, "value": v})
    print(f"   {k}: {r.status_code}")

# 4. Upload session as secret file
print("4. Uploading session...")
session_path = r"C:\Users\danie\Documents\BOT\huntera\huntera_session.json"
with open(session_path, "r") as f:
    session_content = f.read()
r = requests.put(
    f"https://api.render.com/v1/services/{new_sid}/secret-files/HUNTERA_SESSION",
    headers=h,
    json={"content": session_content}
)
print(f"   Session: {r.status_code}")

# 5. Deploy
print("5. Deploying...")
time.sleep(5)
r = requests.post(f"https://api.render.com/v1/services/{new_sid}/deploys", headers=h, json={})
print(f"   Deploy: {r.status_code}")

print(f"\nNova URL: {new_sid}")
print("Aguardando build... (3 min)")
time.sleep(180)

# 6. Test
print("6. Testando...")
for path in ["/health", "/status"]:
    try:
        url = f"https://bot-huntera.onrender.com{path}"
        r = requests.get(url, timeout=60)
        print(f"   {path}: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"   {path}: ERRO - {e}")
