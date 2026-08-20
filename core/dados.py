import time
import requests
import pandas as pd


TENTATIVAS_MAXIMAS = 3
DELAY_ENTRE_TENTATIVAS = 1.0


def _fazer_requisicao(url, params, tentativas=TENTATIVAS_MAXIMAS):
    ultimo_erro = None
    for tentativa in range(tentativas):
        try:
            resposta = requests.get(url, params=params, timeout=15)

            if resposta.status_code == 429:
                tempo_reset = int(resposta.headers.get("Retry-After", 10))
                print(f"  Rate limit atingido. Aguardando {tempo_reset}s...")
                time.sleep(tempo_reset)
                continue

            if resposta.status_code == 418:
                print("  IP banido pela Binance. Aguardando 60s...")
                time.sleep(60)
                continue

            if resposta.status_code != 200:
                ultimo_erro = f"HTTP {resposta.status_code}: {resposta.text[:100]}"
                if tentativa < tentativas - 1:
                    time.sleep(DELAY_ENTRE_TENTATIVAS * (tentativa + 1))
                    continue
                raise requests.exceptions.RequestException(ultimo_erro)

            dados = resposta.json()

            if isinstance(dados, dict) and "code" in dados:
                raise ValueError(f"Erro da Binance: {dados.get('msg', 'desconhecido')}")

            return dados

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            ultimo_erro = str(e)
            if tentativa < tentativas - 1:
                time.sleep(DELAY_ENTRE_TENTATIVAS * (tentativa + 1))
                continue

    raise Exception(f"Falha apos {tentativas} tentativas: {ultimo_erro}")


def buscar_candles(par="BTCUSDT", intervalo="15m", limite=200):
    par = par.upper().strip()
    if par.endswith(".P"):
        par = par[:-2]

    url_spot = "https://api.binance.com/api/v3/klines"
    params = {"symbol": par, "interval": intervalo, "limit": limite}

    try:
        dados = _fazer_requisicao(url_spot, params)
    except Exception:
        url_futuros = "https://fapi.binance.com/fapi/v1/klines"
        dados = _fazer_requisicao(url_futuros, params)

    if not dados or not isinstance(dados, list):
        raise ValueError(f"Dados invalidos para {par}. Verifique se o par existe na Binance.")

    df = pd.DataFrame(dados, columns=[
        "abertura_tempo", "open", "high", "low", "close", "volume",
        "fechamento_tempo", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def buscar_historico(par, intervalo, total_candles, end_time=None):
    par = par.upper().strip()
    if par.endswith(".P"):
        par = par[:-2]

    todos_candles = []
    restante = total_candles

    while restante > 0:
        bloco = min(restante, 1000)
        params = {"symbol": par, "interval": intervalo, "limit": bloco}
        if end_time:
            params["endTime"] = end_time

        url = "https://api.binance.com/api/v3/klines"
        try:
            dados = _fazer_requisicao(url, params)
        except Exception:
            url = "https://fapi.binance.com/fapi/v1/klines"
            dados = _fazer_requisicao(url, params)

        if not dados:
            break

        todos_candles = dados + todos_candles
        end_time = dados[0][0] - 1
        restante -= len(dados)

        if len(dados) < bloco:
            break

        time.sleep(0.3)

    if not todos_candles:
        raise ValueError(f"Nenhum candle encontrado para {par} ({intervalo})")

    df = pd.DataFrame(todos_candles, columns=[
        "abertura_tempo", "open", "high", "low", "close", "volume",
        "fechamento_tempo", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df.drop_duplicates(subset="abertura_tempo").reset_index(drop=True)
    return df
