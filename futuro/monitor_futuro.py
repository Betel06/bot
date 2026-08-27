import sys
import os
import json
import time
import threading
import logging
import collections
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))

import requests

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

for _h in logging.getLogger().handlers:
    _h.formatter.converter = lambda *a: datetime.now(BRT).timetuple()


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

from tvDatafeed import TvDatafeed, Interval

# ===================== CONFIGURACOES (igual ao Pine) =====================
ATIVOS = [
    {"symbol": "BINANCE:COLLECTUSDT.P", "timeframe": "3m", "display": "COLLECT/USDT"},
    {"symbol": "BINANCE:BTWUSDT.P", "timeframe": "15m", "display": "BTW/USDT"},
]

TV_INTERVALS = {
    "1m": Interval.in_1_minute,
    "3m": Interval.in_3_minute,
    "5m": Interval.in_5_minute,
    "15m": Interval.in_15_minute,
    "30m": Interval.in_30_minute,
    "1h": Interval.in_1_hour,
    "4h": Interval.in_4_hour,
}

BB_LENGTH = 20
BB_MULT = 2.0
VOL_MULTIPLIER = 1.2
ALVO_MULTIPLo = 2.0
CHECK_INTERVAL_SECONDS = 15
# ========================================================================

ESTADO = {
    "modo": "BOLLINGER",
    "ativos": len(ATIVOS),
    "ultima_rodada": None,
    "sinais_gerados": 0,
}

RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "futuro_resultados.json")


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


def carregar_resultados():
    return carregar_json(RESULTADOS_FILE, {"wins": 0, "losses": 0, "total_lucro": 0.0, "historico": []})


def calcular_sinais(df, bb_length, bb_mult, vol_multiplier):
    import pandas as pd
    import numpy as np
    df = df.copy()
    df["basis"] = df["close"].rolling(bb_length).mean()
    df["stdev"] = df["close"].rolling(bb_length).std(ddof=0)
    df["upper_band"] = df["basis"] + bb_mult * df["stdev"]
    df["lower_band"] = df["basis"] - bb_mult * df["stdev"]

    df["vol_media"] = df["volume"].rolling(20).mean()
    df["volume_ok"] = df["volume"] >= df["vol_media"] * vol_multiplier

    df["tocou_inferior"] = df["close"] <= df["lower_band"]
    df["tocou_superior"] = df["close"] >= df["upper_band"]

    df["entrada_compra"] = df["tocou_inferior"] & df["volume_ok"]
    df["entrada_venda"] = df["tocou_superior"] & df["volume_ok"]

    # Stop = low/high da vela, R:R = alvoMultiplo
    df["stop_compra"] = df["low"]
    df["alvo_compra"] = df["close"] + (df["close"] - df["low"]) * ALVO_MULTIPLo
    df["stop_venda"] = df["high"]
    df["alvo_venda"] = df["close"] - (df["high"] - df["close"]) * ALVO_MULTIPLo

    return df


def tocar_som():
    try:
        import winsound
        winsound.Beep(1000, 700)
    except Exception:
        print("\a")


def notificar(titulo, mensagem):
    try:
        from plyer import notification
        notification.notify(title=titulo, message=mensagem, timeout=10)
    except Exception:
        pass


def enviar_telegram(mensagem):
    try:
        from futuro.telegram import enviar_mensagem
        enviar_mensagem(mensagem)
    except Exception:
        pass


tv_client = None


def get_tv_client():
    global tv_client
    if tv_client is None:
        tv_client = TvDatafeed()
    return tv_client


def buscar_candles_tv(symbol, timeframe, limit=100):
    tv = get_tv_client()
    interval = TV_INTERVALS.get(timeframe)
    if not interval:
        raise ValueError(f"Timeframe nao suportado: {timeframe}")
    df = tv.get_hist(symbol, exchange="binance", interval=interval, n_bars=limit)
    if df is None or df.empty:
        raise ValueError(f"Sem dados para {symbol}")
    df = df.reset_index()
    df = df.rename(columns={"datetime": "abertura_tempo"})
    return df


def monitor_loop():
    time.sleep(10)

    try:
        from futuro.telegram import enviar_mensagem
        enviar_mensagem(
            "🟢⚡ SMC BOT BOLLINGER ONLINE!\n"
            "Monitorando:\n"
            "- COLLECT/USDT (3m)\n"
            "- BTW/USDT (15m)\n"
            f"Estrategia: Bandas de Bollinger ({BB_LENGTH}, {BB_MULT}x) + Volume {VOL_MULTIPLIER}x"
        )
    except Exception:
        pass

    ultimos_timestamps = {ativo["symbol"]: None for ativo in ATIVOS}
    resultados = carregar_resultados()

    rodada = 0
    while True:
        rodada += 1
        agora = datetime.now(BRT)

        for ativo in ATIVOS:
            symbol = ativo["symbol"]
            display = ativo["display"]
            timeframe = ativo["timeframe"]

            try:
                df = buscar_candles_tv(symbol, timeframe, limit=100)
                df = calcular_sinais(df, BB_LENGTH, BB_MULT, VOL_MULTIPLIER)

                vela = df.iloc[-2]
                ts = vela["abertura_tempo"]

                if ultimos_timestamps[symbol] != ts:
                    ultimos_timestamps[symbol] = ts

                    if vela["entrada_compra"]:
                        entrada = vela["close"]
                        stop = vela["stop_compra"]
                        alvo = vela["alvo_compra"]
                        msg = (f"[{display} {timeframe} | {agora:%d/%m %H:%M}]\n"
                               f"COMPRA\n"
                               f"Entrada: {entrada:.6f}\n"
                               f"Stop Loss: {stop:.6f}\n"
                               f"Take Win: {alvo:.6f}\n"
                               f"R:R 1:{ALVO_MULTIPLo:.0f}")
                        print(msg)
                        logging.info(msg)
                        tocar_som()
                        notificar(f"COMPRA {display}", msg)
                        enviar_telegram(msg)
                        ESTADO["sinais_gerados"] += 1

                        resultados["historico"].append({
                            "par": display,
                            "sinal": "COMPRA",
                            "preco": float(entrada),
                            "stop": float(stop),
                            "alvo": float(alvo),
                            "data": agora.strftime("%d/%m %H:%M"),
                        })
                        salvar_json(RESULTADOS_FILE, resultados)

                    elif vela["entrada_venda"]:
                        entrada = vela["close"]
                        stop = vela["stop_venda"]
                        alvo = vela["alvo_venda"]
                        msg = (f"[{display} {timeframe} | {agora:%d/%m %H:%M}]\n"
                               f"VENDA\n"
                               f"Entrada: {entrada:.6f}\n"
                               f"Stop Loss: {stop:.6f}\n"
                               f"Take Win: {alvo:.6f}\n"
                               f"R:R 1:{ALVO_MULTIPLo:.0f}")
                        print(msg)
                        logging.info(msg)
                        tocar_som()
                        notificar(f"VENDA {display}", msg)
                        enviar_telegram(msg)
                        ESTADO["sinais_gerados"] += 1

                        resultados["historico"].append({
                            "par": display,
                            "sinal": "VENDA",
                            "preco": float(entrada),
                            "stop": float(stop),
                            "alvo": float(alvo),
                            "data": agora.strftime("%d/%m %H:%M"),
                        })
                        salvar_json(RESULTADOS_FILE, resultados)

                    else:
                        logging.info(f"[{display} {timeframe}] Sem sinal - preco: {vela['close']:.6f}")

            except Exception as e:
                logging.error(f"[{display} {timeframe}] Erro: {e}")

        ESTADO["ultima_rodada"] = agora.strftime("%d/%m %H:%M:%S")
        logging.info(f"[Rodada {rodada}] {ESTADO['sinais_gerados']} sinais | {len(ATIVOS)} ativos")

        time.sleep(CHECK_INTERVAL_SECONDS)


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
        return "SMC Bot Bollinger Online! Sinais: {}".format(ESTADO["sinais_gerados"])

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        r = carregar_resultados()
        return {
            "bot": "futuro_bollinger",
            "status": "online",
            "estrategia": "Bollinger Bands",
            "parametros": {
                "bb_length": BB_LENGTH,
                "bb_mult": BB_MULT,
                "vol_multiplier": VOL_MULTIPLIER,
            },
            "ativos": [{"symbol": a["symbol"], "timeframe": a["timeframe"]} for a in ATIVOS],
            "sinais_gerados": ESTADO["sinais_gerados"],
            "ultima_rodada": ESTADO["ultima_rodada"],
            "historico": r.get("historico", [])[-12:],
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

    MONITOR_THREAD = threading.Thread(target=monitor_loop, daemon=True)
    MONITOR_THREAD.start()

    ping_thread = threading.Thread(target=keep_alive_loop, daemon=True)
    ping_thread.start()

    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    criar_app()
