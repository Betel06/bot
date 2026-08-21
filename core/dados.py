import time
import requests
import pandas as pd


TENTATIVAS_MAXIMAS = 3
DELAY_ENTRE_TENTATIVAS = 1.0

URL_SPOT = "https://api.binance.com/api/v3/klines"
URL_FUTUROS = "https://fapi.binance.com/fapi/v1/klines"

BYBIT_URL = "https://api.bybit.com/v5/market/kline"
OKX_URL = "https://www.okx.com/api/v5/market/candles"

BYBIT_INTERVALO = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15",
    "30m": "30", "1h": "60", "2h": "120", "4h": "240",
}
OKX_INTERVALO = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1H", "2h": "2H", "4h": "4H",
}

COLUNAS_PADRAO = [
    "abertura_tempo", "open", "high", "low", "close", "volume",
    "fechamento_tempo", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore"
]

ULTIMA_FONTE = {"nome": None}


def _url_por_mercado(mercado):
    if str(mercado).lower() in ("futuros", "futuro", "futures", "fapi"):
        return URL_FUTUROS
    return URL_SPOT


def _eh_futuros(mercado):
    return str(mercado).lower() in ("futuros", "futuro", "futures", "fapi")


def _par_okx(par, mercado):
    """BTCUSDT -> BTC-USDT (spot) ou BTC-USDT-SWAP (futuros)."""
    p = par.upper().strip()
    if p.endswith(".P"):
        p = p[:-2]
    base = p[:-4] if p.endswith("USDT") else p
    return "{}-USDT-SWAP".format(base) if _eh_futuros(mercado) else "{}-USDT".format(base)


def _req(url, params, tentativas=TENTATIVAS_MAXIMAS):
    ultimo_erro = None
    for tentativa in range(tentativas):
        try:
            resposta = requests.get(url, params=params, timeout=15)
            if resposta.status_code == 429:
                tempo_reset = int(resposta.headers.get("Retry-After", 10))
                print(f"  Rate limit atingido. Aguardando {tempo_reset}s...")
                time.sleep(tempo_reset)
                continue
            if resposta.status_code != 200:
                ultimo_erro = f"HTTP {resposta.status_code}: {resposta.text[:100]}"
                if tentativa < tentativas - 1:
                    time.sleep(DELAY_ENTRE_TENTATIVAS * (tentativa + 1))
                    continue
                raise requests.exceptions.RequestException(ultimo_erro)
            return resposta.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            ultimo_erro = str(e)
            if tentativa < tentativas - 1:
                time.sleep(DELAY_ENTRE_TENTATIVAS * (tentativa + 1))
                continue
    raise Exception(f"Falha apos {tentativas} tentativas: {ultimo_erro}")


# ---------------------------------------------------------------- FONTES ----
# Cada fonte retorna lista [[ms, o, h, l, c, v], ...] ordenada do mais antigo
# para o mais novo, ou levanta excecao.


def _fonte_binance(par, intervalo, limite, mercado="spot", end_ms=None):
    params = {"symbol": par, "interval": intervalo, "limit": min(limite, 1000)}
    if end_ms:
        params["endTime"] = end_ms
    dados = _req(_url_por_mercado(mercado), params)
    if not isinstance(dados, list):
        raise ValueError("resposta binance invalida")
    return [[int(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in dados]


def _fonte_bybit(par, intervalo, limite, mercado="spot", end_ms=None):
    categoria = "linear" if _eh_futuros(mercado) else "spot"
    iv = BYBIT_INTERVALO.get(intervalo)
    if not iv:
        raise ValueError("intervalo nao suportado no bybit: {}".format(intervalo))
    params = {"category": categoria, "symbol": par, "interval": iv,
              "limit": min(limite, 1000)}
    if end_ms:
        params["end"] = end_ms
    j = _req(BYBIT_URL, params)
    if j.get("retCode") != 0:
        raise ValueError("bybit: {}".format(j.get("retMsg", "?")))
    lista = j.get("result", {}).get("list") or []
    linhas = [[int(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in lista]
    linhas.reverse()
    return linhas


def _fonte_okx(par, intervalo, limite, mercado="spot", end_ms=None):
    inst_id = _par_okx(par, mercado)
    iv = OKX_INTERVALO.get(intervalo)
    if not iv:
        raise ValueError("intervalo nao suportado na okx: {}".format(intervalo))
    params = {"instId": inst_id, "bar": iv, "limit": min(limite, 300)}
    if end_ms:
        params["after"] = end_ms
    j = _req(OKX_URL, params)
    if j.get("code") != "0":
        raise ValueError("okx: {}".format(j.get("msg", "?")))
    lista = j.get("data") or []
    linhas = [[int(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in lista]
    linhas.reverse()
    return linhas


FONTES = [
    ("binance", _fonte_binance),
    ("bybit", _fonte_bybit),
    ("okx", _fonte_okx),
]


def _obter_linhas(par, intervalo, limite, mercado, end_ms=None):
    """Tenta as fontes em ordem; retorna linhas normalizadas."""
    erros = []
    minimo_util = min(30, limite)
    for nome, fn in FONTES:
        try:
            linhas = fn(par, intervalo, limite, mercado, end_ms=end_ms)
            if len(linhas) >= minimo_util:
                ULTIMA_FONTE["nome"] = nome
                return linhas
            erros.append("{}: {} candles".format(nome, len(linhas)))
        except Exception as e:
            erros.append("{}: {}".format(nome, str(e)[:80]))
    raise Exception("Todas as fontes falharam para {}: {}".format(
        par, " | ".join(erros)))


def _df_de_linhas(linhas):
    df = pd.DataFrame(linhas, columns=["abertura_tempo", "open", "high",
                                       "low", "close", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().reset_index(drop=True)
    extras = pd.DataFrame(0.0, index=df.index,
                          columns=["fechamento_tempo", "quote_volume",
                                   "trades", "taker_buy_base",
                                   "taker_buy_quote", "ignore"])
    return pd.concat([df, extras], axis=1)[COLUNAS_PADRAO]


def _par_limpo(par):
    p = par.upper().strip()
    return p[:-2] if p.endswith(".P") else p


def buscar_candles(par="BTCUSDT", intervalo="15m", limite=200, mercado="spot"):
    linhas = _obter_linhas(_par_limpo(par), intervalo, limite, mercado)
    return _df_de_linhas(linhas)


def buscar_historico(par, intervalo, total_candles, end_time=None, mercado="spot"):
    todos = []
    restante = int(total_candles)
    cursor = end_time

    while restante > 0:
        bloco = min(restante, 1000)
        linhas = _obter_linhas(_par_limpo(par), intervalo, bloco, mercado,
                               end_ms=cursor)
        if not linhas:
            break
        todos = linhas + todos
        cursor = int(linhas[0][0]) - 1
        restante -= len(linhas)
        if len(linhas) < bloco:
            break
        time.sleep(0.3)

    if not todos:
        raise ValueError("Nenhum candle encontrado para {} ({})".format(
            par, intervalo))

    df = _df_de_linhas(todos)
    df = df.drop_duplicates(subset="abertura_tempo").reset_index(drop=True)
    return df
