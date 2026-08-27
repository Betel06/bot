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
import ccxt
import pandas as pd
import numpy as np

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

# ===================== CONFIGURACOES =====================
ATIVOS = [
    {"symbol": "COLLECT/USDT", "timeframe": "3m"},
    {"symbol": "BTW/USDT", "timeframe": "15m"},
]

BB_LENGTH = 20
BB_MULT = 2.0
VOL_MULTIPLIER = 1.2
CHECK_INTERVAL_SECONDS = 15
# =========================================================

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


def buscar_candles(exchange, symbol, timeframe, limit=100):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def calcular_sinais(df, bb_length, bb_mult, vol_multiplier):
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

    exchanges = {}
    for ativo in ATIVOS:
        exchanges[ativo["symbol"]] = ccxt.binance({"enableRateLimit": True})

    ultimos_timestamps = {ativo["symbol"]: None for ativo in ATIVOS}
    resultados = carregar_resultados()

    rodada = 0
    while True:
        rodada += 1
        agora = datetime.now(BRT)

        for ativo in ATIVOS:
            symbol = ativo["symbol"]
            timeframe = ativo["timeframe"]
            exchange = exchanges[symbol]

            try:
                df = buscar_candles(exchange, symbol, timeframe, limit=100)
                df = calcular_sinais(df, BB_LENGTH, BB_MULT, VOL_MULTIPLIER)

                vela = df.iloc[-2]
                ts = vela["timestamp"]

                if ultimos_timestamps[symbol] != ts:
                    ultimos_timestamps[symbol] = ts
                    hora_local = ts.tz_convert(agora.tzinfo)

                    if vela["entrada_compra"]:
                        msg = (f"[{symbol} {timeframe} | {hora_local:%d/%m %H:%M}] "
                               f"SINAL DE COMPRA - preco: {vela['close']:.6f}")
                        print(msg)
                        logging.info(msg)
                        tocar_som()
                        notificar(f"Sinal de COMPRA - {symbol} ({timeframe})", msg)
                        enviar_telegram(msg)
                        ESTADO["sinais_gerados"] += 1

                        resultados["historico"].append({
                            "par": symbol,
                            "sinal": "COMPRA",
                            "preco": float(vela["close"]),
                            "data": agora.strftime("%d/%m %H:%M"),
                        })
                        salvar_json(RESULTADOS_FILE, resultados)

                    elif vela["entrada_venda"]:
                        msg = (f"[{symbol} {timeframe} | {hora_local:%d/%m %H:%M}] "
                               f"SINAL DE VENDA - preco: {vela['close']:.6f}")
                        print(msg)
                        logging.info(msg)
                        tocar_som()
                        notificar(f"Sinal de VENDA - {symbol} ({timeframe})", msg)
                        enviar_telegram(msg)
                        ESTADO["sinais_gerados"] += 1

                        resultados["historico"].append({
                            "par": symbol,
                            "sinal": "VENDA",
                            "preco": float(vela["close"]),
                            "data": agora.strftime("%d/%m %H:%M"),
                        })
                        salvar_json(RESULTADOS_FILE, resultados)

                    else:
                        logging.info(f"[{symbol} {timeframe}] Sem sinal - preco: {vela['close']:.6f}")

            except Exception as e:
                logging.error(f"[{symbol} {timeframe}] Erro: {e}")

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
