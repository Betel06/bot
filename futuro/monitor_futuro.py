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

# ===================== BANCA FAKE =====================
BANCO_INICIAL = 100.0
ALAVANCAGEM = 2.0
RISCO_POR_TRADE = 0.02
# ========================================================================

ESTADO = {
    "modo": "BOLLINGER",
    "ativos": len(ATIVOS),
    "ultima_rodada": None,
    "sinais_gerados": 0,
}

RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "futuro_resultados.json")
BANCA_FILE = os.path.join(BOT_DIR, "logs", "futuro_banca.json")


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
        json.dump(dados, f, indent=2, ensure_ascii=False)


def carregar_resultados():
    return carregar_json(RESULTADOS_FILE, {"wins": 0, "losses": 0, "total_lucro": 0.0, "historico": []})


def carregar_banca():
    padrao = {
        "banca": BANCO_INICIAL,
        "banca_inicial": BANCO_INICIAL,
        "alavancagem": ALAVANCAGEM,
        "wins": 0,
        "losses": 0,
        "total_lucro": 0.0,
        "posicoes_abertas": {},
        "historico": [],
    }
    return carregar_json(BANCA_FILE, padrao)


def abrir_posicao(banca_data, display, symbol, sinal, entrada, stop, alvo):
    risk_per_unit = abs(entrada - stop)
    if risk_per_unit == 0:
        return None, None

    tamanho_usd = banca_data["banca"] * RISCO_POR_TRADE * ALAVANCAGEM
    risco_usd = tamanho_usd * risk_per_unit / entrada
    lucro_pot = tamanho_usd * abs(alvo - entrada) / entrada

    pos_id = f"{symbol}_{int(time.time())}"
    posicao = {
        "id": pos_id,
        "par": display,
        "symbol": symbol,
        "sinal": sinal,
        "entrada": float(entrada),
        "stop": float(stop),
        "alvo": float(alvo),
        "tamanho_usd": float(tamanho_usd),
        "risco_usd": float(risco_usd),
        "lucro_pot": float(lucro_pot),
        "data_entrada": datetime.now(BRT).strftime("%d/%m %H:%M"),
    }
    banca_data["posicoes_abertas"][pos_id] = posicao
    salvar_json(BANCA_FILE, banca_data)
    return posicao, pos_id


def fechar_posicao(banca_data, pos_id, motivo, preco_saida):
    pos = banca_data["posicoes_abertas"].pop(pos_id, None)
    if not pos:
        return

    entrada = pos["entrada"]
    tamanho = pos["tamanho_usd"]
    sinal = pos["sinal"]

    if sinal == "COMPRA":
        pnl_pct = (preco_saida - entrada) / entrada
    else:
        pnl_pct = (entrada - preco_saida) / entrada

    pnl_usd = tamanho * pnl_pct

    banca_data["banca"] += pnl_usd
    banca_data["total_lucro"] += pnl_usd
    if pnl_usd >= 0:
        banca_data["wins"] += 1
    else:
        banca_data["losses"] += 1

    resultado = {
        "par": pos["par"],
        "sinal": sinal,
        "entrada": entrada,
        "saida": float(preco_saida),
        "motivo": motivo,
        "pnl_usd": round(pnl_usd, 4),
        "banca": round(banca_data["banca"], 4),
        "data": datetime.now(BRT).strftime("%d/%m %H:%M"),
    }
    banca_data["historico"].append(resultado)
    salvar_json(BANCA_FILE, banca_data)

    emoji = "WIN" if pnl_usd >= 0 else "LOSS"
    msg = (
        f"{'🟢' if pnl_usd >= 0 else '🔴'} {emoji} - {pos['par']} [{sinal}]\n"
        f"Entrada: {entrada:.6f}\n"
        f"Saida ({motivo}): {preco_saida:.6f}\n"
        f"P/L: {'+' if pnl_usd >= 0 else ''}{pnl_usd:.4f} USDT\n"
        f"Banca: {banca_data['banca']:.2f} USDT"
    )
    return msg


def calcular_sinais(df, bb_length, bb_mult, vol_multiplier):
    import pandas as pd
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


def formatar_painel(banca_data):
    banca = banca_data["banca"]
    inicial = banca_data["banca_inicial"]
    lucro = banca_data["total_lucro"]
    win = banca_data["wins"]
    loss = banca_data["losses"]
    total = win + loss
    wr = (win / total * 100) if total > 0 else 0
    abertas = len(banca_data["posicoes_abertas"])
    lucro_pct = ((banca - inicial) / inicial * 100) if inicial > 0 else 0

    painel = (
        f"{'='*30}\n"
        f"📊 PAINEL BOLLINGER\n"
        f"{'='*30}\n"
        f"💰 Banca: {banca:.2f} USDT\n"
        f"📈 Lucro: {'+' if lucro >=0 else ''}{lucro:.2f} USDT ({'+' if lucro_pct >=0 else ''}{lucro_pct:.1f}%)\n"
        f"🎯 Win Rate: {wr:.1f}% ({win}W / {loss}L)\n"
        f"📦 Posicoes abertas: {abertas}\n"
        f"{'='*30}\n"
    )
    return painel


def monitor_loop():
    time.sleep(10)

    banca_data = carregar_banca()

    try:
        enviar_telegram(
            f"🟢⚡ BOLLINGER BOT ONLINE!\n"
            f"{'='*30}\n"
            f"💰 Banca: {banca_data['banca']:.2f} USDT\n"
            f"🔧 Alavancagem: {ALAVANCAGEM}x\n"
            f"📊 Risco/trade: {RISCO_POR_TRADE*100:.0f}%\n"
            f"{'='*30}\n"
            f"Monitorando:\n"
            f"- COLLECT/USDT (3m)\n"
            f"- BTW/USDT (15m)\n"
            f"{'='*30}"
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
                candle_low = float(vela["low"])
                candle_high = float(vela["high"])
                candle_close = float(vela["close"])

                # ---- Checar posicoes abertas ----
                pos_para_fechar = []
                for pos_id, pos in list(banca_data["posicoes_abertas"].items()):
                    if pos["symbol"] != symbol:
                        continue
                    if pos["sinal"] == "COMPRA":
                        if candle_low <= pos["stop"]:
                            pos_para_fechar.append((pos_id, "Stop Loss", pos["stop"]))
                        elif candle_high >= pos["alvo"]:
                            pos_para_fechar.append((pos_id, "Take Win", pos["alvo"]))
                    else:
                        if candle_high >= pos["stop"]:
                            pos_para_fechar.append((pos_id, "Stop Loss", pos["stop"]))
                        elif candle_low <= pos["alvo"]:
                            pos_para_fechar.append((pos_id, "Take Win", pos["alvo"]))

                for pos_id, motivo, preco in pos_para_fechar:
                    msg = fechar_posicao(banca_data, pos_id, motivo, preco)
                    if msg:
                        print(msg)
                        logging.info(msg)
                        enviar_telegram(msg)

                # ---- Novo sinal ----
                if ultimos_timestamps[symbol] != ts:
                    ultimos_timestamps[symbol] = ts

                    tem_posicao_aberta = any(
                        p["symbol"] == symbol for p in banca_data["posicoes_abertas"].values()
                    )

                    if vela["entrada_compra"] and not tem_posicao_aberta:
                        entrada = candle_close
                        stop = vela["stop_compra"]
                        alvo = vela["alvo_compra"]
                        pos, pos_id = abrir_posicao(banca_data, display, symbol, "COMPRA", entrada, stop, alvo)
                        if pos:
                            msg = (
                                f"🔔 NOVA COMPRA - {display}\n"
                                f"{'='*30}\n"
                                f"Entrada: {entrada:.6f}\n"
                                f"Stop Loss: {stop:.6f}\n"
                                f"Take Win: {alvo:.6f}\n"
                                f"R:R 1:{ALVO_MULTIPLo:.0f}\n"
                                f"{'='*30}\n"
                                f"💰 Tamanho: {pos['tamanho_usd']:.2f} USDT\n"
                                f"📊 Risco: {pos['risco_usd']:.4f} USDT\n"
                                f"🎯 Lucro pot: {pos['lucro_pot']:.4f} USDT\n"
                                f"{'='*30}"
                            )
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

                    elif vela["entrada_venda"] and not tem_posicao_aberta:
                        entrada = candle_close
                        stop = vela["stop_venda"]
                        alvo = vela["alvo_venda"]
                        pos, pos_id = abrir_posicao(banca_data, display, symbol, "VENDA", entrada, stop, alvo)
                        if pos:
                            msg = (
                                f"🔔 NOVA VENDA - {display}\n"
                                f"{'='*30}\n"
                                f"Entrada: {entrada:.6f}\n"
                                f"Stop Loss: {stop:.6f}\n"
                                f"Take Win: {alvo:.6f}\n"
                                f"R:R 1:{ALVO_MULTIPLo:.0f}\n"
                                f"{'='*30}\n"
                                f"💰 Tamanho: {pos['tamanho_usd']:.2f} USDT\n"
                                f"📊 Risco: {pos['risco_usd']:.4f} USDT\n"
                                f"🎯 Lucro pot: {pos['lucro_pot']:.4f} USDT\n"
                                f"{'='*30}"
                            )
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
                        logging.info(f"[{display} {timeframe}] Sem sinal - preco: {candle_close:.6f}")

            except Exception as e:
                logging.error(f"[{display} {timeframe}] Erro: {e}")

        ESTADO["ultima_rodada"] = agora.strftime("%d/%m %H:%M:%S")
        logging.info(f"[Rodada {rodada}] {ESTADO['sinais_gerados']} sinais | Banca: {banca_data['banca']:.2f}")

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
        b = carregar_banca()
        return f"Bot Bollinger Online! Banca: {b['banca']:.2f} USDT | Sinais: {ESTADO['sinais_gerados']}"

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        b = carregar_banca()
        r = carregar_resultados()
        win = b["wins"]
        loss = b["losses"]
        total = win + loss
        wr = (win / total * 100) if total > 0 else 0
        lucro_pct = ((b["banca"] - b["banca_inicial"]) / b["banca_inicial"] * 100) if b["banca_inicial"] > 0 else 0

        return {
            "bot": "futuro_bollinger",
            "status": "online",
            "estrategia": "Bollinger Bands",
            "banca": {
                "atual": round(b["banca"], 2),
                "inicial": b["banca_inicial"],
                "alavancagem": b["alavancagem"],
                "lucro": round(b["total_lucro"], 4),
                "lucro_pct": round(lucro_pct, 1),
                "win_rate": round(wr, 1),
                "wins": win,
                "losses": loss,
            },
            "posicoes_abertas": len(b["posicoes_abertas"]),
            "sinais_gerados": ESTADO["sinais_gerados"],
            "ultima_rodada": ESTADO["ultima_rodada"],
            "historico": b.get("historico", [])[-12:],
        }

    @app.route("/debug")
    def debug():
        try:
            viva = MONITOR_THREAD.is_alive()
        except Exception:
            viva = False
        b = carregar_banca()
        return {
            "thread_viva": viva,
            "estado": ESTADO,
            "banca": b["banca"],
            "posicoes_abertas": b["posicoes_abertas"],
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
