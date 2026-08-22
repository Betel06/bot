import sys
import os
import json
import time
import threading
import logging
import collections
from datetime import datetime

import requests

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

LOG_BUFFER = collections.deque(maxlen=200)


class _BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            LOG_BUFFER.append(self.format(record))
        except Exception:
            pass


_bufh = _BufferHandler()
_bufh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_bufh)

from spot.config import PARES, STOP_PCT, ROI_TABELA, INTERVALO_MONITOR
from spot.strategy import analisar
from spot.telegram import carregar_config, enviar_mensagem, editar_mensagem, fixar_mensagem, formatar_sinal
from core.dados import buscar_historico


POSICOES_FILE = os.path.join(BOT_DIR, "logs", "posicoes.json")
RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "resultados.json")
TABELA_FILE = os.path.join(BOT_DIR, "logs", "tabela_msg.json")

ENTRADA_USD = float(os.environ.get("SPOT_ENTRADA", "1.0"))
FUTURO_URL = os.environ.get("FUTURO_URL", "https://bot-futuro.onrender.com")

ESTADO = {
    "modo": "RSI",
    "ultima_rodada": None,
    "sinais_gerados": 0,
}


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
        tag = "WIN ✅"
        emoji = "🟢🟢"
    else:
        tag = "LOSS ❌"
        emoji = "🟢🔴"

    texto = (
        "{0} TRADER SPOT | {1}\n"
        "----------------------------\n"
        "\n"
        "Par: {2} ({3})\n"
        "Entrada: ${4:.6f}\n"
        "Saida: ${5:.6f}\n"
        "\n"
        "Resultado: {6} ({7:+.2f}%)\n"
        "P/L: ${8:+.2f}\n"
    ).format(
        emoji, tag,
        res["par"], res["direcao"],
        float(res["entrada"]),
        float(res["preco_saida"]),
        res["tipo"],
        float(res["lucro_pct"]),
        float(res["lucro_usd"]),
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
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro * ENTRADA_USD})
                    posicoes_abertas.remove(pos)
                elif preco_alta >= pos["alvo"]:
                    lucro = (pos["alvo"] - pos["entrada"]) / pos["entrada"]
                    resultado.append({**pos, "tipo": "TAKE PROFIT", "preco_saida": pos["alvo"],
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro * ENTRADA_USD})
                    posicoes_abertas.remove(pos)

            pos["preco_atual"] = preco_atual
        except Exception:
            pass

    return resultado


def checar_sinais():
    ESTADO["modo"] = "RSI"
    sinais = []
    for par in PARES:
        try:
            r = analisar(par)
            if r and r["sinal"]:
                sinais.append(r)
        except Exception as e:
            logging.error("[RSI] {} falhou na rodada: {}".format(par, str(e)[:120]))
        time.sleep(0.3)
    return sinais


def _linha_operacao(h, tag_bot):
    emoji = "✅" if h.get("tipo") == "TAKE PROFIT" else "❌"
    direcao = h.get("direcao") or ""
    dir_txt = ""
    if direcao:
        dir_txt = " {}".format("SHORT" if direcao == "VENDA" else "LONG")
    return "{} {}{} ${:+.2f} · {} {}".format(
        emoji, h.get("par", "?"), dir_txt, float(h.get("lucro", 0.0)),
        h.get("data", "?"), tag_bot)


def montar_tabela(resultados_proprios):
    """Monta o painel combinado dos dois bots (spot + futuro)."""
    r = resultados_proprios

    minhas_pos = carregar_posicoes_arquivo(POSICOES_FILE, [])
    nomes_spot = [p.get("par", "?").replace("USDT", "") for p in minhas_pos][:6]
    linhas = [
        "📊 PAINEL DOS TRADERS 📊",
        "═══════════════════════════",
        "🟢 SPOT | ${:.2f}/op".format(ENTRADA_USD),
        "W {} | L {} | P/L ${:+.2f}".format(
            r["wins"], r["losses"], r.get("total_lucro", 0.0)),
        "📂 Abertas ({}): {}".format(
            len(minhas_pos), ", ".join(nomes_spot) if nomes_spot else "-"),
    ]

    ops = []
    historico_spot = r.get("historico", [])
    for h in historico_spot[-8:]:
        try:
            chave = datetime.strptime(h.get("data", ""), "%d/%m %H:%M")
        except ValueError:
            chave = datetime.min
        ops.append((chave, _linha_operacao(h, "🟢")))

    try:
        fut = requests.get(FUTURO_URL.rstrip("/") + "/status", timeout=10).json()
        if fut.get("status") == "online":
            abertas_fut = fut.get("abertas", []) or []
            nomes_fut = ["{}{}".format(
                x.get("par", "?").replace("USDT", ""),
                "/S" if x.get("direcao") == "VENDA" else "") for x in abertas_fut[:6]]
            linhas += [
                "───────────────────────────",
                "🔵 FUTURO ⚡ IA | ${:.2f}/op".format(float(fut.get("entrada_usd", 0))),
                "W {} | L {} | P/L ${:+.2f}".format(
                    fut.get("wins", 0), fut.get("losses", 0), float(fut.get("pl_usd", 0))),
                "📂 Abertas ({}): {}".format(
                    len(abertas_fut), ", ".join(nomes_fut) if nomes_fut else "-"),
            ]
            for h in (fut.get("historico") or [])[-8:]:
                try:
                    chave = datetime.strptime(h.get("data", ""), "%d/%m %H:%M")
                except ValueError:
                    chave = datetime.min
                ops.append((chave, _linha_operacao(h, "🔵")))
        else:
            raise ValueError("offline")
    except Exception:
        linhas += [
            "───────────────────────────",
            "🔵 FUTURO ⚡ IA | offline",
        ]

    if ops:
        ops.sort(key=lambda t: t[0], reverse=True)
        linhas.append("───────────────────────────")
        linhas.append("📜 ÚLTIMAS OPERAÇÕES")
        for _, linha in ops[:8]:
            linhas.append(linha)

    linhas.append("═══════════════════════════")
    return "\n".join(linhas)


def atualizar_tabela(resultados_proprios):
    """Cria ou edita a mensagem fixada com o painel dos dois bots."""
    try:
        texto = montar_tabela(resultados_proprios)
        estado_tabela = carregar_posicoes_arquivo(TABELA_FILE, {})

        if estado_tabela.get("texto") == texto and estado_tabela.get("message_id"):
            return

        mid = estado_tabela.get("message_id")
        if mid:
            ok, _ = editar_mensagem(mid, texto)
            if not ok:
                ok_novo, novo = enviar_mensagem(texto)
                if ok_novo:
                    fixar_mensagem(novo)
                    mid = novo
        else:
            ok, novo = enviar_mensagem(texto)
            if ok:
                fixar_mensagem(novo)
                mid = novo

        if mid:
            salvar_json_arquivo(TABELA_FILE, {"message_id": mid, "texto": texto})
    except Exception as e:
        logging.error("[TABELA] falha: {}".format(e))


def carregar_posicoes_arquivo(caminho, padrao):
    try:
        if os.path.exists(caminho):
            with open(caminho, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return padrao


def salvar_json_arquivo(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w") as f:
        json.dump(dados, f, indent=2)


def monitor_loop():
    time.sleep(10)

    token, chat_id = carregar_config()
    telegram_ok = token is not None and chat_id is not None

    posicoes_abertas = carregar_posicoes()
    resultados = carregar_resultados()

    if telegram_ok:
        try:
            enviar_mensagem("🟢 TRADER SPOT ONLINE no Render 24/7!\nEstrategia RSI em ATOM, UNI, ADA, LINK e XRP.")
        except Exception as e:
            logging.error("[TELEGRAM] falha no startup: {}".format(e))

    rodada = 0
    intervalo = INTERVALO_MONITOR

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
                    "direcao": res.get("direcao", ""),
                    "tipo": res["tipo"],
                    "lucro": res["lucro_usd"],
                    "data": agora.strftime("%d/%m %H:%M"),
                })

            sinais = checar_sinais()
            ESTADO["ultima_rodada"] = agora.strftime("%d/%m %H:%M:%S")
            ESTADO["sinais_gerados"] += len(sinais)

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

            if telegram_ok:
                atualizar_tabela(resultados)

            logging.info("[Rodada {}] {}W {}L | ${:+.2f} | {} posicoes abertas".format(
                rodada, resultados["wins"], resultados["losses"], resultados["total_lucro"],
                len(posicoes_abertas)))

        except Exception as e:
            logging.error("[ERRO] {}".format(e))

        time.sleep(intervalo)


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
        r = carregar_resultados()
        return "Trader Spot Online! RSI 24/7. Wins: {} | Losses: {}".format(r["wins"], r["losses"])

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        r = carregar_resultados()
        p = carregar_posicoes()
        return {
            "bot": "spot",
            "status": "online",
            "wins": r["wins"],
            "losses": r["losses"],
            "entrada_usd": ENTRADA_USD,
            "pl_usd": round(r["total_lucro"], 4),
            "posicoes_abertas": len(p),
            "monitor": ESTADO,
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

    @app.route("/pares")
    def pares():
        dados = []
        for par in PARES:
            try:
                r = analisar(par)
                if r:
                    dados.append({
                        "par": par.replace("USDT", ""),
                        "preco": round(r["preco"], 6),
                        "rsi": round(r["rsi"], 1),
                        "tendencia": r["tendencia"],
                        "sinal": r["sinal"] or "-",
                    })
            except Exception:
                dados.append({"par": par, "erro": True})
        return {"bot": "spot",
                "regra": "COMPRA: RSI<40 + ALTA | VENDA: RSI>70 + BAIXA",
                "pares": dados}

    global MONITOR_THREAD
    MONITOR_THREAD = threading.Thread(target=monitor_loop, daemon=True)
    MONITOR_THREAD.start()

    ping_thread = threading.Thread(target=keep_alive_loop, daemon=True)
    ping_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
