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
    {"symbol": "BINANCE:COLLECTUSDT.P", "timeframe": "3m", "display": "COLLECT/USDT (3m)"},
    {"symbol": "BINANCE:BTWUSDT.P", "timeframe": "5m", "display": "BTW/USDT (5m)"},
    {"symbol": "BINANCE:BTWUSDT.P", "timeframe": "15m", "display": "BTW/USDT (15m)"},
]

# Cada ativo+timeframe vira uma chave propria: posicao e timestamps separados,
# entao o BTW 5m e o BTW 15m operam em paralelo sem bloquear um ao outro.
MIGRACAO_CHAVES = {
    "BINANCE:COLLECTUSDT.P": "BINANCE:COLLECTUSDT.P|3m",
    "BINANCE:BTWUSDT.P": "BINANCE:BTWUSDT.P|5m",
}

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
ALVO_MULTIPLo = 3.0
CHECK_INTERVAL_SECONDS = 15

# Filtro SMC de tendencia: so opera a favor da estrutura (alta = so COMPRA,
# baixa = so VENDA), com a MESMA defasagem do grafico (pivo confirma pivot_len
# velas depois; tendencia muda quando o CLOSE rompe topo/fundo).
FILTRO_SMC = os.environ.get("FILTRO_SMC_TENDENCIA", "1") != "0"
SMC_PIVOT_LEN = int(os.environ.get("SMC_PIVOT_LEN", "10"))

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

SECAO = "futuro_bollinger"

try:
    from core import persist as persist
    PERSIST_DISPONIVEL = persist.configurado()
except Exception:
    persist = None
    PERSIST_DISPONIVEL = False


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


def _banca_padrao():
    return {
        "banca": BANCO_INICIAL,
        "banca_inicial": BANCO_INICIAL,
        "alavancagem": ALAVANCAGEM,
        "wins": 0,
        "losses": 0,
        "total_lucro": 0.0,
        "posicoes_abertas": {},
        "historico": [],
        "ultimos_timestamps": {},
    }


def _merge_banca(origem, padrao):
    dados = dict(padrao)
    if isinstance(origem, dict):
        for k in ["banca", "banca_inicial", "alavancagem", "wins", "losses", "total_lucro"]:
            if k in origem:
                dados[k] = origem[k]
        for k in ["posicoes_abertas", "historico", "ultimos_timestamps"]:
            if isinstance(origem.get(k), (dict, list)):
                dados[k] = origem[k]

    # migra chaves antigas (so symbol) para chave symbol|timeframe
    posicoes = {}
    for pid, p in (dados.get("posicoes_abertas") or {}).items():
        if isinstance(p, dict):
            p = dict(p)
            p["symbol"] = MIGRACAO_CHAVES.get(p.get("symbol"), p.get("symbol") or p["symbol"])
            posicoes[pid] = p
    dados["posicoes_abertas"] = posicoes

    timestamps = {}
    for k, v in (dados.get("ultimos_timestamps") or {}).items():
        timestamps[MIGRACAO_CHAVES.get(k, k)] = v
    dados["ultimos_timestamps"] = timestamps

    return dados


def carregar_banca():
    """GitHub eh a fonte da verdade; disco local eh fallback."""
    origem = None
    if persist is not None:
        try:
            estado = persist.carregar_estado()
            if isinstance(estado, dict) and isinstance(estado.get(SECAO), dict):
                origem = estado[SECAO]
        except Exception:
            pass

    if origem is None:
        origem = carregar_json(BANCA_FILE, {})

    return _merge_banca(origem, _banca_padrao())


def salvar_banca(banca_data):
    try:
        salvar_json(BANCA_FILE, banca_data)
    except Exception:
        pass
    if persist is not None:
        try:
            persist.salvar_secao(SECAO, dict(banca_data))
        except Exception:
            pass


def carregar_resultados():
    return carregar_json(RESULTADOS_FILE, {"wins": 0, "losses": 0, "total_lucro": 0.0, "historico": []})


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
    salvar_banca(banca_data)
    return posicao, pos_id


def fechar_posicao(banca_data, pos_id, motivo, preco_saida):
    pos = banca_data["posicoes_abertas"].pop(pos_id, None)
    if not pos:
        return None

    entrada = pos["entrada"]
    tamanho = pos.get("tamanho_usd", 0)
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
    salvar_banca(banca_data)

    emoji = "WIN" if pnl_usd >= 0 else "LOSS"
    msg = (
        f"{'🟢' if pnl_usd >= 0 else '🔴'} {emoji} - {pos['par']} [{sinal}]\n"
        f"Entrada: {entrada:.6f}\n"
        f"Saida ({motivo}): {preco_saida:.6f}\n"
        f"P/L: {'+' if pnl_usd >= 0 else ''}{pnl_usd:.4f} USDT\n"
        f"Banca: {banca_data['banca']:.2f} USDT"
    )
    return msg


def calcular_estrutura_smc(df, pivot_len):
    """Estrutura SMC identica ao Pine do grafico: pivos confirmados pivot_len
    velas depois (mesma defasagem), tendencia so muda quando o CLOSE rompe
    topo/fundo (BOS/CHoCH). Retorna coluna smc_tendencia."""
    import numpy as np
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    ph = np.full(n, np.nan)
    pl = np.full(n, np.nan)
    for i in range(pivot_len, n - pivot_len):
        if hi[i] == (hi[i-pivot_len:i+pivot_len+1]).max():
            ph[i] = hi[i]
        if lo[i] == (lo[i-pivot_len:i+pivot_len+1]).min():
            pl[i] = lo[i]
    ultimo_topo = None
    ultimo_fundo = None
    tendencia = "indefinida"
    tendencias = []
    for i in range(n):
        k = i - pivot_len
        if k >= 0 and not np.isnan(ph[k]):
            ultimo_topo = float(ph[k])
        if k >= 0 and not np.isnan(pl[k]):
            ultimo_fundo = float(pl[k])
        prev_close = cl[i-1] if i >= 1 else np.nan
        if ultimo_topo is not None and not np.isnan(prev_close) and cl[i] > ultimo_topo >= prev_close:
            tendencia = "alta"
        if ultimo_fundo is not None and not np.isnan(prev_close) and cl[i] < ultimo_fundo <= prev_close:
            tendencia = "baixa"
        tendencias.append(tendencia)
    df["smc_tendencia"] = tendencias
    return df


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

    if FILTRO_SMC:
        df = calcular_estrutura_smc(df, SMC_PIVOT_LEN)
        df["entrada_compra"] = df["entrada_compra"] & (df["smc_tendencia"] == "alta")
        df["entrada_venda"] = df["entrada_venda"] & (df["smc_tendencia"] == "baixa")

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


def checar_fechamentos(banca_data, symbol, df, novo_index):
    """Ve se as posicoes abertas deste symbol foram tocadas nas velas novas."""
    msgs = []
    for k in range(novo_index):
        vela = df.iloc[k]
        candle_low = float(vela["low"])
        candle_high = float(vela["high"])

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
                msgs.append(msg)
    return msgs


def processar_vela(banca_data, ativo, symbol, display, timeout_tf, vela, agora):
    """Abre posicao se a vela tiver sinal. Retorna lista de mensagens."""
    msgs = []
    candle_low = float(vela["low"])
    candle_high = float(vela["high"])
    candle_close = float(vela["close"])

    tem_posicao_aberta = any(
        p["symbol"] == symbol for p in banca_data["posicoes_abertas"].values()
    )

    if bool(vela["entrada_compra"]) and not tem_posicao_aberta:
        pos, pos_id = abrir_posicao(banca_data, display, symbol, "COMPRA", candle_close,
                                    float(vela["stop_compra"]), float(vela["alvo_compra"]))
        if pos:
            msg = (
                f"🔔 NOVA COMPRA - {display}\n"
                f"{'='*30}\n"
                f"Entrada: {candle_close:.6f}\n"
                f"Stop Loss: {pos['stop']:.6f}\n"
                f"Take Win: {pos['alvo']:.6f}\n"
                f"R:R 1:{ALVO_MULTIPLo:.0f}\n"
                f"{'='*30}\n"
                f"💰 Tamanho: {pos['tamanho_usd']:.2f} USDT\n"
                f"📊 Risco: {pos['risco_usd']:.4f} USDT\n"
                f"🎯 Lucro pot: {pos['lucro_pot']:.4f} USDT\n"
                f"{'='*30}"
            )
            msgs.append(msg)
            ESTADO["sinais_gerados"] += 1

    elif bool(vela["entrada_venda"]) and not tem_posicao_aberta:
        pos, pos_id = abrir_posicao(banca_data, display, symbol, "VENDA", candle_close,
                                    float(vela["stop_venda"]), float(vela["alvo_venda"]))
        if pos:
            msg = (
                f"🔔 NOVA VENDA - {display}\n"
                f"{'='*30}\n"
                f"Entrada: {candle_close:.6f}\n"
                f"Stop Loss: {pos['stop']:.6f}\n"
                f"Take Win: {pos['alvo']:.6f}\n"
                f"R:R 1:{ALVO_MULTIPLo:.0f}\n"
                f"{'='*30}\n"
                f"💰 Tamanho: {pos['tamanho_usd']:.2f} USDT\n"
                f"📊 Risco: {pos['risco_usd']:.4f} USDT\n"
                f"🎯 Lucro pot: {pos['lucro_pot']:.4f} USDT\n"
                f"{'='*30}"
            )
            msgs.append(msg)
            ESTADO["sinais_gerados"] += 1

    if not msgs:
        logging.info(f"[{display} {timeout_tf}] Sem sinal - preco: {candle_close:.6f}")
    return msgs


def monitor_loop():
    import pandas as pd
    time.sleep(10)

    banca_data = carregar_banca()

    try:
        enviar_telegram(
            f"🟢⚡ BOLLINGER BOT ONLINE!\n"
            f"{'='*30}\n"
            f"💰 Banca: {banca_data['banca']:.2f} USDT\n"
            f"🔧 Alavancagem: {ALAVANCAGEM}x\n"
            f"📊 Risco/trade: {RISCO_POR_TRADE*100:.0f}%\n"
            f"🔒 Persistencia: {'GitHub ON' if PERSIST_DISPONIVEL else 'local'}\n"
            f"🧭 Filtro SMC: {'ON (so a favor da estrutura)' if FILTRO_SMC else 'off'}\n"
            f"{'='*30}\n"
            f"Monitorando:\n"
            f"- COLLECT/USDT (3m)\n"
            f"- BTW/USDT (5m)\n"
            f"- BTW/USDT (15m)\n"
            f"{'='*30}"
        )
    except Exception:
        pass

    resultados = carregar_resultados()

    rodada = 0
    while True:
        rodada += 1
        agora = datetime.now(BRT)

        for ativo in ATIVOS:
            symbol = ativo["symbol"]
            display = ativo["display"]
            timeframe = ativo["timeframe"]
            chave = f"{symbol}|{timeframe}"

            try:
                df = buscar_candles_tv(symbol, timeframe, limit=100)
                df = calcular_sinais(df, BB_LENGTH, BB_MULT, VOL_MULTIPLIER)

                ult_timestamps = banca_data.setdefault("ultimos_timestamps", {})
                ult_bruto = ult_timestamps.get(chave)

                # a partir de qual indice processar (velas fechadas novas)
                inicio = 0
                if ult_bruto is not None:
                    ref = pd.to_datetime(ult_bruto)
                    for i in range(len(df) - 1):
                        if pd.to_datetime(df.iloc[i]["abertura_tempo"]) > ref:
                            inicio = i
                            break
                    else:
                        inicio = len(df) - 1
                else:
                    # primeiro boot: processa so a ultima vela fechada (iloc[-2])
                    inicio = len(df) - 2

                # checar fechamentos de posicoes nas velas novas
                msgs = checar_fechamentos(banca_data, chave, df, inicio)

                # processar velas novas (sinais)
                for i in range(inicio, len(df) - 1):
                    vela = df.iloc[i]
                    msgs += processar_vela(banca_data, ativo, chave, display, timeframe, vela, agora)
                    ult_timestamps[chave] = str(df.iloc[i]["abertura_tempo"])

                if inicio < len(df) - 1:
                    ult_timestamps[chave] = str(df.iloc[len(df) - 2]["abertura_tempo"])
                    salvar_banca(banca_data)

                for m in msgs:
                    print(m)
                    logging.info(m)
                    tocar_som()
                    enviar_telegram(m)

                resultados_atuais = banca_data.get("historico", [])[-5:]
                if resultados_atuais:
                    salvar_json(RESULTADOS_FILE, {
                        "wins": banca_data["wins"],
                        "losses": banca_data["losses"],
                        "total_lucro": banca_data["total_lucro"],
                        "historico": resultados_atuais,
                    })

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
        win = b["wins"]
        loss = b["losses"]
        total = win + loss
        wr = (win / total * 100) if total > 0 else 0
        lucro_pct = ((b["banca"] - b["banca_inicial"]) / b["banca_inicial"] * 100) if b["banca_inicial"] > 0 else 0

        return {
            "bot": "futuro_bollinger",
            "status": "online",
            "estrategia": "Bollinger Bands",
            "filtro_smc": {
                "ativo": FILTRO_SMC,
                "pivot_len": SMC_PIVOT_LEN,
                "regra": "COMPRA so em tendencia ALTA | VENDA so em tendencia BAIXA",
            },
            "persistencia": "github" if PERSIST_DISPONIVEL else "local",
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
            "ultimos_timestamps": b.get("ultimos_timestamps", {}),
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