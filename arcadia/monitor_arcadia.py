import os
import time
import json
import logging
from playwright.sync_api import sync_playwright
from flask import Flask
from threading import Thread

# Configurações básicas
LOG_FILE = "../logs/ai_decisions_arcadia.jsonl"
app = Flask(__name__)

@app.route('/health')
def health(): return "OK", 200

def run_bot():
    print("Iniciando bot Arcadia 24/7...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://arcadia-mmo.com")
        
        # 1. Login
        print("Logando...")
        page.locator("button:has-text('Conecte-se')").click()
        time.sleep(10)
        
        # 2. Seleção de Personagem
        print("Selecionando personagem...")
        page.locator("text=Unordinary").click()
        time.sleep(2)
        page.locator("text=Jogar").click()
        time.sleep(5)
        
        # 3. Farm (loop de ataque)
        print("Farmando...")
        while True:
            page.keyboard.press("1")
            time.sleep(0.5)
            # Auditoria simples
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps({"ts": time.time(), "acao": "farm_key_1"}) + "\n")

if __name__ == "__main__":
    # Inicia o servidor Keep-Alive para o Render
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))).start()
    run_bot()
