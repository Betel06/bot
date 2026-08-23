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

from spot.config import PARES, STOP_PCT, ROI_TABELA, INTERVALO_MONITOR
from spot.strategy import analisar
from spot.telegram import carregar_config, enviar_mensagem, editar_mensagem, fixar_mensagem, formatar_sinal
from core.dados import buscar_historico


POSICOES_FILE = os.path.join(BOT_DIR, "logs", "posicoes.json")
RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "resultados.json")
TABELA_FILE = os.path.join(BOT_DIR, "logs", "tabela_msg.json")

ENTRADA_USD = float(os.environ.get("SPOT_ENTRADA", "1.0"))
FUTURO_URL = os.environ.get("FUTURO_URL", "https://bot-futuro.onrender.com")
ENTRADA_FUT_PADRAO = float(os.environ.get("FUTURO_ENTRADA", "2.0"))
BANCO_SPOT = float(os.environ.get("SPOT_BANCO_INICIAL", "10.0"))
BANCO_FUT = float(os.environ.get("FUTURO_BANCO_INICIAL", "10.0"))


def _linha_banco(banco, pl):
    if banco <= 0:
        return ""
    return "🏦 Banco: ${:.2f} de ${:.2f} ({:+.1f}%)".format(
        banco + pl, banco, pl / banco * 100)

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
    """Monta o painel combinado dos dois bots (spot + futuro).
    Fonte primaria: historico real do chat no Telegram (via MTProto)."""
    r = resultados_proprios

    tg = None
    try:
        from core.tg_history import ler_estado_do_chat
        tg = ler_estado_do_chat()
    except Exception as e:
        logging.warning("[TG] leitura do historico falhou: {}".format(e))

    minhas_pos = carregar_posicoes_arquivo(POSICOES_FILE, [])
    if minhas_pos:
        pos_spot = [{"par": p.get("par", "?")} for p in minhas_pos]
    elif tg:
        pos_spot = [a for a in tg["abertas"] if a["bot"] == "spot"]
    else:
        pos_spot = []
    nomes_spot = [p.get("par", "?").replace("USDT", "") for p in pos_spot][:6]

    if tg:
        st_spot = tg["spot"]
        pl_spot = st_spot["pl"]
        wins_spot = st_spot["wins"]
        losses_spot = st_spot["losses"]
    else:
        pl_spot = r.get("total_lucro", 0.0)
        wins_spot = r["wins"]
        losses_spot = r["losses"]

    linhas = [
        "📊 PAINEL DOS TRADERS 📊",
        "═══════════════════════════",
        "🟢 SPOT | ${:.2f}/op".format(ENTRADA_USD),
        "W {} | L {} | P/L ${:+.2f}".format(wins_spot, losses_spot, pl_spot),
        _linha_banco(BANCO_SPOT, pl_spot),
        "📂 Abertas ({}): {}".format(
            len(pos_spot), ", ".join(nomes_spot) if nomes_spot else "-"),
    ]

    ops = []
    fonte_spot_hist = tg["spot"]["historico"] if tg else r.get("historico", [])
    for h in fonte_spot_hist[-8:]:
        try:
            chave = datetime.strptime(h.get("data", ""), "%d/%m %H:%M")
        except ValueError:
            chave = datetime.min
        ops.append((chave, _linha_operacao(h, "🟢")))

    abertas_fut = []
    fut_status_ok = False
    try:
        fut = requests.get(FUTURO_URL.rstrip("/") + "/status", timeout=10).json()
        if fut.get("status") == "online":
            fut_status_ok = True
            abertas_fut = fut.get("abertas", []) or []
    except Exception:
        pass
    if tg and (not fut_status_ok or not abertas_fut):
        rec = [a for a in tg["abertas"] if a["bot"] == "futuro"]
        if len(rec) >= len(abertas_fut):
            abertas_fut = [{"par": a["par"], "direcao": a["direcao"]} for a in rec]

    nomes_fut = ["{}{}".format(
        x.get("par", "?").replace("USDT", ""),
        "/S" if x.get("direcao") == "VENDA" else "") for x in abertas_fut[:6]]

    if tg:
        st_fut = tg["futuro"]
        bloco_fut = [
            "───────────────────────────",
            "🔵 FUTURO ⚡ IA | ${:.2f}/op".format(ENTRADA_FUT_PADRAO),
            "W {} | L {} | P/L ${:+.2f}".format(
                st_fut["wins"], st_fut["losses"], st_fut["pl"]),
            _linha_banco(BANCO_FUT, st_fut["pl"]),
            "📂 Abertas ({}): {}".format(
                len(abertas_fut), ", ".join(nomes_fut) if nomes_fut else "-"),
        ]
        for h in tg["futuro"]["historico"][-8:]:
            try:
                chave = datetime.strptime(h.get("data", ""), "%d/%m %H:%M")
            except ValueError:
                chave = datetime.min
            ops.append((chave, _linha_operacao(h, "🔵")))
    elif fut_status_ok:
        pl_fut_api = float(fut.get("pl_usd", 0))
        bloco_fut = [
            "───────────────────────────",
            "🔵 FUTURO ⚡ IA | ${:.2f}/op".format(float(fut.get("entrada_usd", 0))),
            "W {} | L {} | P/L ${:+.2f}".format(
                fut.get("wins", 0), fut.get("losses", 0), pl_fut_api),
            _linha_banco(BANCO_FUT, pl_fut_api),
            "📂 Abertas ({}): {}".format(
                len(abertas_fut), ", ".join(nomes_fut) if nomes_fut else "-"),
        ]
    else:
        bloco_fut = [
            "───────────────────────────",
            "🔵 FUTURO ⚡ IA | offline",
        ]
    linhas += bloco_fut

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


def restaurar_do_remoto():
    """Restaura posicoes/resultados/tabela do estado salvo no GitHub."""
    try:
        from core.persist import carregar_estado
        secao = (carregar_estado() or {}).get("spot")
        if not isinstance(secao, dict):
            return
        if not os.path.exists(POSICOES_FILE) and isinstance(secao.get("posicoes"), list):
            salvar_json_arquivo(POSICOES_FILE, secao["posicoes"])
        if not os.path.exists(RESULTADOS_FILE) and isinstance(secao.get("resultados"), dict):
            salvar_json_arquivo(RESULTADOS_FILE, secao["resultados"])
        if not os.path.exists(TABELA_FILE) and isinstance(secao.get("tabela"), dict):
            salvar_json_arquivo(TABELA_FILE, secao["tabela"])
        logging.info("[PERSIST] estado do spot restaurado do GitHub")
    except Exception as e:
        logging.warning("[PERSIST] restauracao falhou: {}".format(e))


def sincronizar_remoto(posicoes, resultados):
    """Salva estado atual do spot no GitHub (posicoes + resultados + tabela)."""
    try:
        from core.persist import salvar_secao
        copia = dict(resultados)
        copia["historico"] = list(resultados.get("historico", []))[-100:]
        ok = salvar_secao("spot", {"posicoes": posicoes, "resultados": copia})
        tabela = carregar_posicoes_arquivo(TABELA_FILE, {})
        if tabela.get("message_id"):
            salvar_secao("tabela", tabela)
        if not ok:
            logging.error("[PERSIST] falha ao salvar estado do spot no GitHub")
    except Exception as e:
        logging.error("[PERSIST] excecao ao sincronizar: {}".format(e))


def reconciliar_com_telegram(posicoes_abertas, resultados):
    """Usa o historico real do chat como fonte da verdade no boot."""
    try:
        from core.tg_history import ler_estado_do_chat
        tg = ler_estado_do_chat(forcar=True)
        if not tg:
            return posicoes_abertas, resultados

        s = tg["spot"]
        if s["wins"] + s["losses"] > resultados.get("wins", 0) + resultados.get("losses", 0):
            resultados["wins"] = s["wins"]
            resultados["losses"] = s["losses"]
            resultados["total_lucro"] = round(s["pl"], 4)
            resultados["historico"] = s["historico"][-100:]
            salvar_resultados(resultados)
            logging.info("[TG] placar SPOT recuperado: {}W {}L ${:+.2f}".format(
                s["wins"], s["losses"], s["pl"]))

        if not posicoes_abertas:
            rec = []
            for a in tg["abertas"]:
                if a["bot"] != "spot":
                    continue
                rec.append({
                    "par": a["par"],
                    "direcao": a["direcao"],
                    "entrada": a["entrada"],
                    "stop": a["stop"],
                    "alvo": a["alvo"],
                    "data": a["data"],
                    "preco_atual": a["entrada"],
                })
            if rec:
                salvar_posicoes(rec)
                posicoes_abertas = rec
                logging.info("[TG] {} posicoes SPOT reconstruidas do chat".format(len(rec)))
    except Exception as e:
        logging.warning("[TG] reconciliacao falhou: {}".format(e))
    return posicoes_abertas, resultados


def monitor_loop():
    time.sleep(10)

    token, chat_id = carregar_config()
    telegram_ok = token is not None and chat_id is not None

    restaurar_do_remoto()
    posicoes_abertas = carregar_posicoes()
    resultados = carregar_resultados()
    posicoes_abertas, resultados = reconciliar_com_telegram(
        posicoes_abertas, resultados)

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

            salvar_posicoes(posicoes_abertas)
            salvar_resultados(resultados)

            if telegram_ok:
                atualizar_tabela(resultados)

            if novos_resultados or abriu_posicao:
                sincronizar_remoto(posicoes_abertas, resultados)

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
