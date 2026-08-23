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

from b3.config import (ATIVO, CONTRATOS, VALOR_PONTO, CUSTO_TRADE, BANCO_INICIAL,
                       INTERVALO_MONITOR, MERCADO, MAX_SINAIS_DIA, STOP_DIARIO_PCT,
                       META_DIARIA_PCT, RISCO_MAX_TRADE_REAIS, STUDY_MODE,
                       INTERVALO_ESTUDO, FECHAMENTO_FORCADO,
                       pode_operar_agora, janela_atual, agora_brt)
from core.ai_brain import analisar_com_ia, ia_ativa
from core.dados_b3 import buscar_candles_b3, ULTIMA_FONTE_B3
from b3.telegram import carregar_config, enviar_mensagem, formatar_sinal, formatar_resultado
from b3.config import dia_util

POSICOES_FILE = os.path.join(BOT_DIR, "logs", "b3_posicoes.json")
RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "b3_resultados.json")

ESTADO = {
    "modo": "-",
    "modelo": os.environ.get("AI_MODEL", "gemini-3.6-flash"),
    "ultima_rodada": None,
    "ultimo_estudo": None,
    "janela": "-",
    "fonte_dados": "-",
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
    return carregar_json(RESULTADOS_FILE, {
        "banco_inicial": BANCO_INICIAL, "wins": 0, "losses": 0,
        "total_lucro": 0.0, "historico": [],
    })


def checar_posicoes(posicoes_abertas, forcar_fechamento=False):
    resultado = []
    for pos in list(posicoes_abertas):
        try:
            df = buscar_candles_b3(pos["par"], "1m", 10)
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

            if not fechou and forcar_fechamento:
                fechou = ("FECHAMENTO SESSAO", float(df["close"].iloc[-1]))

            if fechou:
                tipo, saida = fechou
                pontos = (saida - pos["entrada"]) if pos["direcao"] == "COMPRA" \
                    else (pos["entrada"] - saida)
                lucro_reais = pontos * VALOR_PONTO * CONTRATOS - CUSTO_TRADE
                resultado.append({**pos, "tipo": tipo, "preco_saida": saida,
                                  "pontos": pontos,
                                  "lucro_reais": lucro_reais})
                posicoes_abertas.remove(pos)
        except Exception:
            pass

    return resultado


def checar_sinais(janela):
    usar_ia = ia_ativa()
    ESTADO["modo"] = "IA" if usar_ia else "-"
    sinais = []
    if not usar_ia:
        return sinais

    r = analisar_com_ia(ATIVO, mercado=MERCADO)
    ESTADO["janela"] = janela
    if r and r["sinal"]:
        risco_reais = abs(float(r["preco"]) - float(r["stop"])) * VALOR_PONTO * CONTRATOS
        if risco_reais > RISCO_MAX_TRADE_REAIS:
            logging.warning("[RISCO] setup descartado: stop estrutural R$%.2f "
                            "> limite R$%.2f (capital insuficiente p/ WDO)" % (
                                risco_reais, RISCO_MAX_TRADE_REAIS))
        else:
            sinais.append(r)
    return sinais


def restaurar_do_remoto():
    """Restaura posicoes/resultados do estado salvo no GitHub."""
    try:
        from core.persist import carregar_estado
        secao = (carregar_estado() or {}).get("b3")
        if not isinstance(secao, dict):
            return
        if not os.path.exists(POSICOES_FILE) and isinstance(secao.get("posicoes"), list):
            salvar_json(POSICOES_FILE, secao["posicoes"])
        if not os.path.exists(RESULTADOS_FILE) and isinstance(secao.get("resultados"), dict):
            salvar_json(RESULTADOS_FILE, secao["resultados"])
        logging.info("[PERSIST] estado do B3 restaurado do GitHub")
    except Exception as e:
        logging.warning("[PERSIST] restauracao falhou: {}".format(e))


def sincronizar_remoto(posicoes, resultados):
    """Salva estado atual do B3 no GitHub."""
    try:
        from core.persist import salvar_secao
        copia = dict(resultados)
        copia["historico"] = list(resultados.get("historico", []))[-100:]
        ok = salvar_secao("b3", {"posicoes": posicoes, "resultados": copia})
        if not ok:
            logging.error("[PERSIST] falha ao salvar estado do B3 no GitHub")
    except Exception as e:
        logging.error("[PERSIST] excecao ao sincronizar: {}".format(e))


def monitor_loop():
    time.sleep(10)

    token, chat_id = carregar_config()
    telegram_ok = token is not None and chat_id is not None

    restaurar_do_remoto()
    posicoes_abertas = carregar_posicoes()
    resultados = carregar_resultados()

    dia_hoje = agora_brt().date()
    controle = {"sinais_hoje": 0, "pl_dia": 0.0, "bloqueado_motivo": None,
                "ultimo_estudo_ts": 0, "ultimo_candle_sinal": None,
                "ultimo_candle_estudo": None}

    def candle_novo(par, intervalo, chave):
        """True se o ultimo candle mudou desde a ultima analise (economiza quota IA)."""
        try:
            df = buscar_candles_b3(par, intervalo, 1)
            ts = str(df["abertura_tempo"].iloc[-1])
            if controle[chave] == ts:
                return False
            controle[chave] = ts
            return True
        except Exception:
            return True

    def resetar_se_novo_dia(agora):
        nonlocal dia_hoje
        if agora.date() != dia_hoje:
            dia_hoje = agora.date()
            controle["sinais_hoje"] = 0
            controle["pl_dia"] = 0.0
            controle["bloqueado_motivo"] = None

    try:
        from core.persist import configurado
        logging.info("[PERSIST] persistencia GitHub ativa: {}".format(configurado()))
    except Exception:
        pass

    if telegram_ok:
        try:
            enviar_mensagem(
                "🟡⚡ TRADER B3 ONLINE no Render 24/7!\n"
                "Day trade com IA (SMC) no mini dolar WDO — FASE PAPEL.\n"
                "Banco fake: R$ {:.0f} | 1 contrato | stop diario -{:.0f}%\n"
                "Killzones: 09h00-10h30 / 10h30-12h30 / 15h00-17h00 (BRT)".format(
                    BANCO_INICIAL, STOP_DIARIO_PCT))
        except Exception as e:
            logging.error("[TELEGRAM] falha no startup: {}".format(e))

    rodada = 0

    while True:
        rodada += 1
        agora = agora_brt()

        try:
            resetar_se_novo_dia(agora)

            # Fechamento forcado de posicoes abertas no fim da sessao (day trade).
            if posicoes_abertas and agora.time() >= FECHAMENTO_FORCADO and agora.hour < 19:
                novos = checar_posicoes(posicoes_abertas, forcar_fechamento=True)
                for res in novos:
                    aplicar_resultado(res, resultados, controle, telegram_ok)

            pode, motivo_janela = pode_operar_agora()
            ESTADO["janela"] = motivo_janela

            novos_resultados = []
            if posicoes_abertas:
                novos_resultados = checar_posicoes(posicoes_abertas)
                for res in novos_resultados:
                    aplicar_resultado(res, resultados, controle, telegram_ok)

            sinais = []
            if pode and controle["bloqueado_motivo"] is None \
                    and controle["sinais_hoje"] < MAX_SINAIS_DIA \
                    and not posicoes_abertas:
                if candle_novo(ATIVO, INTERVALO, "ultimo_candle_sinal"):
                    sinais = checar_sinais(motivo_janela)
                    ESTADO["ultima_rodada"] = agora.strftime("%d/%m %H:%M:%S")
                    ESTADO["sinais_gerados"] += len(sinais)
            elif not pode and STUDY_MODE and ia_ativa() and dia_util(agora):
                ts = time.time()
                if ts - controle["ultimo_estudo_ts"] >= INTERVALO_ESTUDO \
                        and candle_novo("DXY", "60m", "ultimo_candle_estudo"):
                    controle["ultimo_estudo_ts"] = ts
                    analisar_com_ia("DXY", mercado=MERCADO, estudo=True)
                    ESTADO["ultimo_estudo"] = datetime.utcnow().strftime("%d/%m %H:%M")

            for s in sinais:
                posicoes_abertas.append({
                    "par": s["par"],
                    "direcao": s["sinal"],
                    "entrada": s["preco"],
                    "stop": s["stop"],
                    "alvo": s["alvo"],
                    "data": agora.strftime("%d/%m %H:%M"),
                    "preco_atual": s["preco"],
                })
                controle["sinais_hoje"] += 1

                logging.info("[SINAL] {} {} | {:.1f} pts".format(s["sinal"], s["par"], s["preco"]))
                if telegram_ok:
                    enviar_mensagem(formatar_sinal(s))

            # Stop diario / meta diaria (percentual do banco inicial).
            limite_stop = BANCO_INICIAL * STOP_DIARIO_PCT / 100.0
            limite_meta = BANCO_INICIAL * META_DIARIA_PCT / 100.0
            if controle["bloqueado_motivo"] is None:
                if controle["pl_dia"] <= -limite_stop:
                    controle["bloqueado_motivo"] = "STOP DIARIO (-R$ %.2f)" % controle["pl_dia"]
                    logging.warning("[GESTAO] {}".format(controle["bloqueado_motivo"]))
                    if telegram_ok:
                        enviar_mensagem("🟡🛑 TRADER B3: STOP DIARIO atingido "
                                        "(R$ {:+.2f} hoje). Sem novos sinais ate amanha.".format(
                                            controle["pl_dia"]))
                elif controle["pl_dia"] >= limite_meta:
                    controle["bloqueado_motivo"] = "META DIARIA (+R$ %.2f)" % controle["pl_dia"]
                    logging.info("[GESTAO] {}".format(controle["bloqueado_motivo"]))
                    if telegram_ok:
                        enviar_mensagem("🟡🎯 TRADER B3: META DIARIA batida "
                                        "(R$ {:+.2f} hoje). Encerrando o dia no lucro.".format(
                                            controle["pl_dia"]))

            salvar_posicoes_e_resultados(posicoes_abertas, resultados)

            if novos_resultados or sinais:
                sincronizar_remoto(posicoes_abertas, resultados)

            fonte = "ok" if ULTIMA_FONTE_B3["ok"] else (ULTIMA_FONTE_B3["erro"] or "?")
            ESTADO["fonte_dados"] = fonte

            if rodada % 12 == 1:
                logging.info("[Rodada {}] {}W {}L | saldo R$ {:.2f} | {} pos abertas | {}".format(
                    rodada, resultados["wins"], resultados["losses"],
                    resultados["banco_inicial"] + resultados["total_lucro"],
                    len(posicoes_abertas), motivo_janela))

        except Exception as e:
            logging.error("[ERRO] {}".format(e))

        time.sleep(INTERVALO_MONITOR)


def aplicar_resultado(res, resultados, controle, telegram_ok):
    tag = "WIN" if res["tipo"] == "TAKE PROFIT" else res["tipo"]
    logging.info("[{}] {} {} | R$ {:+.2f} ({:+.1f} pts)".format(
        tag, res["tipo"], res["par"], res["lucro_reais"], res["pontos"]))

    if telegram_ok:
        enviar_mensagem(formatar_resultado(res))

    if res["lucro_reais"] > 0:
        resultados["wins"] += 1
    else:
        resultados["losses"] += 1
    resultados["total_lucro"] += res["lucro_reais"]
    controle["pl_dia"] += res["lucro_reais"]
    resultados.setdefault("historico", []).append({
        "par": res["par"],
        "direcao": res.get("direcao", ""),
        "tipo": res["tipo"],
        "pontos": round(res["pontos"], 1),
        "lucro": round(res["lucro_reais"], 2),
        "data": agora_brt().strftime("%d/%m %H:%M"),
    })


def salvar_posicoes_e_resultados(posicoes, resultados):
    salvar_json(POSICOES_FILE, posicoes)
    salvar_json(RESULTADOS_FILE, resultados)


def keep_alive_loop():
    url = os.environ.get("RENDER_EXTERNAL_URL") or ("http://127.0.0.1:" + os.environ.get("PORT", "5002"))
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
        return "Trader B3 Online! IA 24/7. Wins: {} | Losses: {}".format(r["wins"], r["losses"])

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        r = carregar_resultados()
        p = carregar_posicoes()
        return {
            "bot": "b3",
            "status": "online",
            "ativo": ATIVO,
            "wins": r["wins"],
            "losses": r["losses"],
            "banco_inicial": r.get("banco_inicial", BANCO_INICIAL),
            "saldo": round(r.get("banco_inicial", BANCO_INICIAL) + r["total_lucro"], 2),
            "pl_reais": round(r["total_lucro"], 2),
            "valor_ponto": VALOR_PONTO,
            "contratos": CONTRATOS,
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
                               "..", "logs", "ai_decisions_b3.jsonl")
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

    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    criar_app()
