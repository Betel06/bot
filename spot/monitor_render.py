import sys
import os
import json
import time
import threading
import logging
from datetime import datetime

import requests

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from spot.config import PARES, STOP_PCT, ROI_TABELA
from spot.strategy import analisar
from spot.telegram import carregar_config, enviar_mensagem, formatar_sinal
from core.dados import buscar_historico


POSICOES_FILE = os.path.join(BOT_DIR, "logs", "posicoes.json")
RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "resultados.json")


def carregar_posicoes():
    try:
        if os.path.exists(POSICOES_FILE):
            with open(POSICOES_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def salvar_posicoes(posicoes):
    os.makedirs(os.path.dirname(POSICOES_FILE), exist_ok=True)
    with open(POSICOES_FILE, "w") as f:
        json.dump(posicoes, f, indent=2)


def carregar_resultados():
    try:
        if os.path.exists(RESULTADOS_FILE):
            with open(RESULTADOS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"wins": 0, "losses": 0, "total_lucro": 0.0, "historico": []}


def salvar_resultados(resultados):
    os.makedirs(os.path.dirname(RESULTADOS_FILE), exist_ok=True)
    with open(RESULTADOS_FILE, "w") as f:
        json.dump(resultados, f, indent=2)


def formatar_resultado(res):
    if res["tipo"] == "TAKE PROFIT":
        tag = "WIN"
    else:
        tag = "LOSS"

    texto = (
        "* {} {}*\n"
        "\n"
        "Par: {}\n"
        "Direcao: {}\n"
        "Entrada: ${:.6f}\n"
        "Saida: ${:.6f}\n"
        "\n"
        "Resultado: {} ({:+.2f}%)\n"
        "Lucro/Perda: ${:+.4f}\n"
    ).format(
        tag, res["tipo"], res["par"],
        res["direcao"],
        res["entrada"],
        res["preco_saida"],
        res["tipo"],
        res["lucro_pct"],
        res["lucro_usd"],
    )
    return texto


def checar_posicoes(posicoes_abertas):
    resultado = []
    for pos in list(posicoes_abertas):
        try:
            df = buscar_historico(pos["par"], "5m", 10)
            if df is None or len(df) == 0:
                continue

            preco_atual = float(df["close"].iloc[-1])
            preco_alta = float(df["high"].iloc[-1])
            preco_baixa = float(df["low"].iloc[-1])

            if pos["direcao"] == "COMPRA":
                if preco_baixa <= pos["stop"]:
                    lucro = (pos["stop"] - pos["entrada"]) / pos["entrada"]
                    resultado.append({**pos, "tipo": "STOP LOSS", "preco_saida": pos["stop"],
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro})
                    posicoes_abertas.remove(pos)
                elif preco_alta >= pos["alvo"]:
                    lucro = (pos["alvo"] - pos["entrada"]) / pos["entrada"]
                    resultado.append({**pos, "tipo": "TAKE PROFIT", "preco_saida": pos["alvo"],
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro})
                    posicoes_abertas.remove(pos)

            pos["preco_atual"] = preco_atual
        except Exception:
            pass

    return resultado


def checar_sinais():
    sinais = []
    for par in PARES:
        try:
            r = analisar(par)
            if r and r["sinal"]:
                sinais.append(r)
        except Exception:
            pass
        time.sleep(0.3)
    return sinais


def monitor_loop():
    time.sleep(10)

    token, chat_id = carregar_config()
    telegram_ok = token is not None and chat_id is not None

    posicoes_abertas = carregar_posicoes()
    resultados = carregar_resultados()

    if telegram_ok:
        enviar_mensagem("[BOT] Monitor ONLINE no Render 24/7!")

    rodada = 0

    while True:
        rodada += 1
        agora = datetime.now()

        try:
            novos_resultados = checar_posicoes(posicoes_abertas)
            for res in novos_resultados:
                tag = "WIN" if res["tipo"] == "TAKE PROFIT" else "LOSS"
                logging.info("[{}] {} {} | ${:+.4f} ({:+.2f}%)".format(
                    tag, res["tipo"], res["par"], res["lucro_usd"], res["lucro_pct"]))

                if telegram_ok:
                    enviar_mensagem(formatar_resultado(res))

                if res["tipo"] == "TAKE PROFIT":
                    resultados["wins"] += 1
                else:
                    resultados["losses"] += 1
                resultados["total_lucro"] += res["lucro_usd"]
                resultados["historico"].append({
                    "par": res["par"],
                    "tipo": res["tipo"],
                    "lucro": res["lucro_usd"],
                    "data": agora.strftime("%d/%m %H:%M"),
                })

            sinais = checar_sinais()

            for s in sinais:
                ja_aberto = any(p["par"] == s["par"] for p in posicoes_abertas)

                if not ja_aberto:
                    posicoes_abertas.append({
                        "par": s["par"],
                        "direcao": s["sinal"],
                        "entrada": s["preco"],
                        "stop": s["stop"],
                        "alvo": s["alvo"],
                        "data": agora.strftime("%d/%m %H:%M"),
                        "preco_atual": s["preco"],
                    })

                    logging.info("[SINAL] {} {} | ${:.6f}".format(s["sinal"], s["par"], s["preco"]))

                    if telegram_ok:
                        enviar_mensagem(formatar_sinal(s))

            salvar_posicoes(posicoes_abertas)
            salvar_resultados(resultados)

            logging.info("[Rodada {}] {}W {}L | ${:+.4f} | {} posicoes abertas".format(
                rodada, resultados["wins"], resultados["losses"], resultados["total_lucro"],
                len(posicoes_abertas)))

        except Exception as e:
            logging.error("[ERRO] {}".format(e))

        time.sleep(300)


def keep_alive_loop():
    url = os.environ.get("RENDER_EXTERNAL_URL") or ("http://127.0.0.1:" + os.environ.get("PORT", "5000"))
    while True:
        try:
            requests.get(url.rstrip("/") + "/health", timeout=30)
        except Exception:
            pass
        time.sleep(600)


if __name__ == "__main__":
    from flask import Flask

    app = Flask(__name__)

    @app.route("/")
    def hello_world():
        return "Bot Spot Online! Rodando 24/7. Wins: {} | Losses: {}".format(
            carregar_resultados()["wins"],
            carregar_resultados()["losses"]
        )

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        r = carregar_resultados()
        p = carregar_posicoes()
        return {
            "status": "online",
            "wins": r["wins"],
            "losses": r["losses"],
            "lucro": r["total_lucro"],
            "posicoes_abertas": len(p),
        }

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    ping_thread = threading.Thread(target=keep_alive_loop, daemon=True)
    ping_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
