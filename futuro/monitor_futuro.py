import sys
import os
import json
import time
import threading
import logging
import collections
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))  # horario de Brasilia fixo (independe do servidor)

import requests

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class _FiltroHealth(logging.Filter):
    def filter(self, record):
        return "/health" not in record.getMessage()


logging.getLogger("werkzeug").addFilter(_FiltroHealth())

LOG_BUFFER = collections.deque(maxlen=2000)


class _BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            LOG_BUFFER.append(self.format(record))
        except Exception:
            pass


_bufh = _BufferHandler()
_bufh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_bufh)

from futuro.config import PARES, PARES_POR_RODADA, INTERVALO_MONITOR, ENTRADA_USD, ALAVANCAGEM, MERCADO
from core.ai_brain import analisar_com_ia, ia_ativa
from core.dados import buscar_historico
from futuro.telegram import carregar_config, enviar_mensagem, formatar_sinal, formatar_resultado

POSICOES_FILE = os.path.join(BOT_DIR, "logs", "futuro_posicoes.json")
RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "futuro_resultados.json")

ESTADO = {
    "modo": "-",
    "modelo": os.environ.get("AI_MODEL", "gemini-3.5-flash"),
    "ultima_rodada": None,
    "sinais_gerados": 0,
}


def carregar_json(caminho, padrao):
    try:
        if os.path.exists(caminho):
            with open(caminho, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return padrao


def salvar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w") as f:
        json.dump(dados, f, indent=2)


def carregar_posicoes():
    return carregar_json(POSICOES_FILE, [])


def carregar_resultados():
    return carregar_json(RESULTADOS_FILE, {"wins": 0, "losses": 0, "total_lucro": 0.0, "historico": []})


def checar_posicoes(posicoes_abertas):
    resultado = []
    for pos in list(posicoes_abertas):
        try:
            df = buscar_historico(pos["par"], "1m", 10, mercado=MERCADO)
            if df is None or len(df) == 0:
                continue

            preco_alta = float(df["high"].iloc[-1])
            preco_baixa = float(df["low"].iloc[-1])

            fechou = None
            if pos["direcao"] == "COMPRA":
                if preco_baixa <= pos["stop"]:
                    fechou = ("STOP LOSS", pos["stop"])
                elif preco_alta >= pos["alvo"]:
                    fechou = ("TAKE PROFIT", pos["alvo"])
            else:
                if preco_alta >= pos["stop"]:
                    fechou = ("STOP LOSS", pos["stop"])
                elif preco_baixa <= pos["alvo"]:
                    fechou = ("TAKE PROFIT", pos["alvo"])

            if fechou:
                tipo, saida = fechou
                if pos["direcao"] == "COMPRA":
                    lucro = (saida - pos["entrada"]) / pos["entrada"]
                else:
                    lucro = (pos["entrada"] - saida) / pos["entrada"]
                resultado.append({**pos, "tipo": tipo, "preco_saida": saida,
                                  "lucro_pct": lucro * 100,
                                  "lucro_usd": lucro * ENTRADA_USD * ALAVANCAGEM,
                                  "alavancagem": ALAVANCAGEM})
                posicoes_abertas.remove(pos)
        except Exception:
            pass

    return resultado


_ROTACAO = {"idx": 0}


def lote_da_rodada():
    """Retorna o proximo lote de pares (rotacao circular pela lista inteira)."""
    n = max(1, min(PARES_POR_RODADA, len(PARES)))
    idx0 = _ROTACAO["idx"] % len(PARES)
    lote = [PARES[(idx0 + i) % len(PARES)] for i in range(n)]
    _ROTACAO["idx"] = (idx0 + n) % len(PARES)
    return lote


def checar_sinais():
    usar_ia = ia_ativa()
    ESTADO["modo"] = "IA" if usar_ia else "-"
    sinais = []
    lote = lote_da_rodada()
    logging.info("[IA] lote da rodada: {}".format(", ".join(lote)))
    for par in lote:
        try:
            if usar_ia:
                r = analisar_com_ia(par, mercado=MERCADO)
            else:
                r = None
            if r and r["sinal"]:
                sinais.append(r)
        except Exception as e:
            logging.error("[IA] {} falhou na rodada: {}".format(par, str(e)[:120]))
        time.sleep(0.3)
    return sinais


def restaurar_do_remoto():
    """Restaura posicoes/resultados do estado salvo no GitHub."""
    try:
        from core.persist import carregar_estado
        secao = (carregar_estado() or {}).get("futuro")
        if not isinstance(secao, dict):
            return
        if not os.path.exists(POSICOES_FILE) and isinstance(secao.get("posicoes"), list):
            salvar_json(POSICOES_FILE, secao["posicoes"])
        if not os.path.exists(RESULTADOS_FILE) and isinstance(secao.get("resultados"), dict):
            salvar_json(RESULTADOS_FILE, secao["resultados"])
        logging.info("[PERSIST] estado do futuro restaurado do GitHub")
    except Exception as e:
        logging.warning("[PERSIST] restauracao falhou: {}".format(e))


def sincronizar_remoto(posicoes, resultados):
    """Salva estado atual do futuro no GitHub."""
    try:
        from core.persist import salvar_secao
        copia = dict(resultados)
        copia["historico"] = list(resultados.get("historico", []))[-100:]
        ok = salvar_secao("futuro", {"posicoes": posicoes, "resultados": copia})
        if not ok:
            logging.error("[PERSIST] falha ao salvar estado do futuro no GitHub")
    except Exception as e:
        logging.error("[PERSIST] excecao ao sincronizar: {}".format(e))


def monitor_loop():
    time.sleep(10)

    token, chat_id = carregar_config()
    telegram_ok = token is not None and chat_id is not None

    restaurar_do_remoto()
    posicoes_abertas = carregar_posicoes()
    resultados = carregar_resultados()

    try:
        from core.persist import configurado
        logging.info("[PERSIST] persistencia GitHub ativa: {}".format(configurado()))
    except Exception:
        pass

    if telegram_ok:
        try:
            enviar_mensagem("🔵⚡ TRADER FUTURO ONLINE no Render 24/7!\nDay trade com IA (SMC) em 12 pares: BTC, ETH, SOL, XRP, DOGE, AVAX, LINK, SUI, BNB, LTC, COLLECT e BTW.")
        except Exception as e:
            logging.error("[TELEGRAM] falha no startup: {}".format(e))

    rodada = 0

    intervalo = INTERVALO_MONITOR
    try:
        if ia_ativa():
            intervalo = int(os.environ.get("AI_INTERVALO", str(INTERVALO_MONITOR)))
            from core.ai_brain import MODELOS as _cadeia
            logging.info("[IA] cerebro ATIVO (cadeia: {}), rodada a cada {}s".format(
                " -> ".join(_cadeia), intervalo))
        else:
            logging.warning("[IA] DESATIVADA - defina AI_ENABLED=1 e GEMINI_API_KEY")
    except Exception:
        pass

    while True:
        rodada += 1
        agora = datetime.now(BRT)

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
                    "direcao": res.get("direcao", ""),
                    "tipo": res["tipo"],
                    "lucro": res["lucro_usd"],
                    "data": agora.strftime("%d/%m %H:%M"),
                })

            sinais = checar_sinais()
            ESTADO["ultima_rodada"] = agora.strftime("%d/%m %H:%M:%S")
            ESTADO["sinais_gerados"] += len(sinais)

            abriu_posicao = False
            for s in sinais:
                ja_aberto = any(p["par"] == s["par"] for p in posicoes_abertas)

                if not ja_aberto:
                    abriu_posicao = True
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

            salvar_posicoes_e_resultados(posicoes_abertas, resultados)

            if novos_resultados or abriu_posicao:
                sincronizar_remoto(posicoes_abertas, resultados)

            logging.info("[Rodada {}] {}W {}L | ${:+.2f} | {} posicoes abertas".format(
                rodada, resultados["wins"], resultados["losses"], resultados["total_lucro"],
                len(posicoes_abertas)))

        except Exception as e:
            logging.error("[ERRO] {}".format(e))

        time.sleep(intervalo)


def salvar_posicoes_e_resultados(posicoes, resultados):
    salvar_json(POSICOES_FILE, posicoes)
    salvar_json(RESULTADOS_FILE, resultados)


def keep_alive_loop():
    url = os.environ.get("RENDER_EXTERNAL_URL") or ("http://127.0.0.1:" + os.environ.get("PORT", "5001"))
    while True:
        try:
            requests.get(url.rstrip("/") + "/health", timeout=30)
        except Exception:
            pass
        time.sleep(600)


def criar_app():
    global MONITOR_THREAD
    from flask import Flask

    app = Flask(__name__)

    @app.route("/")
    def hello_world():
        r = carregar_resultados()
        return "Trader Futuro Online! IA 24/7. Wins: {} | Losses: {}".format(r["wins"], r["losses"])

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        r = carregar_resultados()
        p = carregar_posicoes()
        return {
            "bot": "futuro",
            "status": "online",
            "wins": r["wins"],
            "losses": r["losses"],
            "entrada_usd": ENTRADA_USD,
            "alavancagem": ALAVANCAGEM,
            "pl_usd": round(r["total_lucro"], 4),
            "posicoes_abertas": len(p),
            "abertas": [{"par": x["par"], "direcao": x.get("direcao", "")} for x in p],
            "historico": r.get("historico", [])[-12:],
            "ia": ESTADO,
        }

    @app.route("/debug")
    def debug():
        try:
            viva = MONITOR_THREAD.is_alive()
        except Exception:
            viva = False
        return {
            "thread_viva": viva,
            "estado": ESTADO,
            "logs": list(LOG_BUFFER)[-80:],
        }

    @app.route("/audit")
    def audit():
        arquivo = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "logs", "ai_decisions_futuro.jsonl")
        itens = []
        try:
            with open(arquivo, encoding="utf-8") as f:
                for ln in f.readlines()[-20:]:
                    ln = ln.strip()
                    if ln:
                        try:
                            itens.append(json.loads(ln))
                        except Exception:
                            pass
        except FileNotFoundError:
            pass
        return {"total": len(itens), "decisoes": itens}

    MONITOR_THREAD = threading.Thread(target=monitor_loop, daemon=True)
    MONITOR_THREAD.start()

    ping_thread = threading.Thread(target=keep_alive_loop, daemon=True)
    ping_thread.start()

    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    criar_app()
