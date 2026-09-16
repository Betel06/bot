# futuro/monitor_futuro.py (MODO ESTUDO - BANCA FAKE $50)
import time
import json
import os
from datetime import datetime

# Configuracoes
MOEDAS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT", "ADAUSDT"]
BANCA_INICIAL = 50.0
RISCO_FIXO = 1.0
ALVO_FIXO = 3.0 # 3R
LOG_FILE = "logs/banca_fake.json"

def carregar_banca():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f: return json.load(f)
    return {"banca": BANCO_INICIAL, "trades": []}

def salvar_banca(banca_data):
    with open(LOG_FILE, "w") as f: json.dump(banca_data, f)

def sinal_saca_liquidez(moeda):
    # Logica simulada da V1 (Saca-Liquidez)
    # Em producao, aqui voce integra com a API da Binance/TradingView
    return None

def monitorar():
    print("Bot rodando em Modo Estudo (Banca Fake: $50)...")
    banca_data = carregar_banca()
    
    while True:
        for moeda in MOEDAS:
            sinal = sinal_saca_liquidez(moeda)
            if sinal:
                # Logica de entrada fake
                banca_data["trades"].append({
                    "moeda": moeda, "risco": RISCO_FIXO, "ganho": ALVO_FIXO, 
                    "status": "ABERTO", "data": str(datetime.now())
                })
                salvar_banca(banca_data)
                # Enviar pro Telegram aqui
        time.sleep(60)

if __name__ == "__main__":
    monitorar()
