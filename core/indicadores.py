import pandas as pd
import numpy as np


def calcular_rsi(serie, periodo=14):
    delta = serie.diff()
    ganho = delta.where(delta > 0, 0.0)
    perda = (-delta).where(delta < 0, 0.0)
    media_ganho = ganho.rolling(window=periodo, min_periods=periodo).mean()
    media_perda = perda.rolling(window=periodo, min_periods=periodo).mean()
    rs = media_ganho / media_perda
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calcular_ema(serie, periodo):
    return serie.ewm(span=periodo, adjust=False).mean()


def calcular_macd(serie, rapido=12, lento=26, sinal=9):
    ema_rapido = calcular_ema(serie, rapido)
    ema_lento = calcular_ema(serie, lento)
    macd = ema_rapido - ema_lento
    sinal_macd = calcular_ema(macd, sinal)
    histograma = macd - sinal_macd
    return macd, sinal_macd, histograma


def calcular_bollinger(serie, periodo=20, desvio=2):
    media = serie.rolling(window=periodo).mean()
    std = serie.rolling(window=periodo).std()
    superior = media + desvio * std
    inferior = media - desvio * std
    return superior, media, inferior


def calcular_atr(high, low, close, periodo=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=periodo).mean()
    return atr


def calcular_adx(high, low, close, periodo=14):
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr = calcular_atr(high, low, close, periodo)
    plus_di = 100 * calcular_ema(plus_dm, periodo) / atr
    minus_di = 100 * calcular_ema(minus_dm, periodo) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = calcular_ema(dx, periodo)
    return adx, plus_di, minus_di


def calcular_stochrsi(close, rsi_periodo=14, stoch_periodo=14, k_periodo=3, d_periodo=3):
    rsi = calcular_rsi(close, rsi_periodo)
    rsi_min = rsi.rolling(window=stoch_periodo).min()
    rsi_max = rsi.rolling(window=stoch_periodo).max()
    stochrsi = (rsi - rsi_min) / (rsi_max - rsi_min)
    k = stochrsi.rolling(window=k_periodo).mean() * 100
    d = k.rolling(window=d_periodo).mean()
    return k, d


def calcular_supertrend(high, low, close, periodo=10, multiplicador=3):
    atr = calcular_atr(high, low, close, periodo)
    hl2 = (high + low) / 2
    superior = hl2 + multiplicador * atr
    inferior = hl2 - multiplicador * atr

    supertrend = pd.Series(index=close.index, dtype=float)
    direcao = pd.Series(index=close.index, dtype=float)

    supertrend.iloc[0] = superior.iloc[0]
    direcao.iloc[0] = 1

    for i in range(1, len(close)):
        if close.iloc[i] > superior.iloc[i-1]:
            direcao.iloc[i] = 1
        elif close.iloc[i] < inferior.iloc[i-1]:
            direcao.iloc[i] = -1
        else:
            direcao.iloc[i] = direcao.iloc[i-1]

            if direcao.iloc[i] == 1 and inferior.iloc[i] < inferior.iloc[i-1]:
                inferior.iloc[i] = inferior.iloc[i-1]
            if direcao.iloc[i] == -1 and superior.iloc[i] > superior.iloc[i-1]:
                superior.iloc[i] = superior.iloc[i-1]

        supertrend.iloc[i] = inferior.iloc[i] if direcao.iloc[i] == 1 else superior.iloc[i]

    return supertrend, direcao
