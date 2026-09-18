"""
estrategia.py - Logica de sinais do bot M15 (Breakout de range + volume).

Regra base (hipotese a validar no backtest):
  1. Em cada vela M15 fechada, define uma "faixa de consolidacao" olhando as
     ultimas RANGE_LENGTH velas (alto maximo e baixo minimo do periodo).
  2. Se o CLOSE da vela atual rompe a faixa (acima do alto -> COMPRA, abaixo
     do baixo -> VENDA) com VOLUME acima da media * VOL_MULTIPLIER, gera sinal.
  3. Gestao: stop = extremo oposto do rompimento (com opcao de folga de ATR);
     alvo = RR * (entrada - stop).

Melhorias (filtros de qualidade, ativos e medidos no backtest):
  - FILTRO_CORPO: so aceita rompimento com corpo forte e pavio pequeno (evita
    falso rompimento / rejeicao). Mesmo principio do Pine estrategia_btc_pro_m15.
  - STOP_ATR: stop nao fica "colado" no extremo, ganha folga de ATR*mult
    (absorve agulhada sem ser levado antes da hora).
  - FILTRO_MACD: usa MACD como filtro de direcao adicional a tendencia HTF.
  - FILTRO_HTF: tendencia 1h (preco vs EMA) define se aceita compra/venda.

Retorna DataFrame com colunas de sinal, stop e alvo (mesmo padrao dos outros bots).
"""

import pandas as pd
import numpy as np


def _atr(df, length=14):
    """Average True Range sobre o df (ohlcv)."""
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    prev = np.roll(cl, 1)
    prev[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - prev), np.abs(lo - prev)))
    atr = pd.Series(tr).rolling(length).mean().to_numpy()
    return atr


def _macd_ok(closes, fast=12, slow=26, signal=9):
    """Retorna bool array: True onde MACD > sinal (momentum comprador)."""
    s = pd.Series(closes)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return (macd_line > signal_line).to_numpy()


def calcular_sinais(df, range_length, vol_multiplier, vol_window,
                    rr, requer_fechamento, filtro_htf, htf_ema_period,
                    filtro_corpo=True, max_wick_ratio=0.4,
                    filtro_macd=True, stop_atr=False, atr_mult=1.5, atr_len=14,
                    dias_operacao=None):
    """Gera sinais de breakout. df M15 com colunas ohlcv + abertura_tempo.

    dias_operacao: lista opcional de dayofweek (0=Seg .. 6=Dom) em que se
    aceita sinal. None = opera todos os dias. Baseado no padrao robusto
    Quinta(3)+Sexta(4) encontrado no backtest.
    """
    df = df.copy()
    n = len(df)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    op = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float)

    # Media movel de volume
    vol_media = pd.Series(vol).rolling(vol_window).mean().to_numpy()
    volume_ok = np.zeros(n, dtype=bool)
    for i in range(n):
        if not np.isnan(vol_media[i]) and vol[i] >= vol_media[i] * vol_multiplier:
            volume_ok[i] = True

    # Faixa de consolidacao (altero max / baixo min das ultimas RANGE_LENGTH
    # velas, EXCLUINDO a vela atual para nao olhar o futuro).
    range_high = np.full(n, np.nan)
    range_low = np.full(n, np.nan)
    for i in range(n):
        start = max(0, i - range_length)
        end = i  # exclusivo
        if end - start < 1:
            continue
        range_high[i] = hi[start:end].max()
        range_low[i] = lo[start:end].min()

    # ATR para folga de stop (opcional)
    atr = _atr(df, atr_len) if stop_atr else np.zeros(n)

    # Qualidade da vela (corpo forte, pavio pequeno)
    corpo = np.abs(cl - op)
    wick_up = hi - np.maximum(op, cl)
    wick_dn = np.minimum(op, cl) - lo

    compra = np.zeros(n, dtype=bool)
    venda = np.zeros(n, dtype=bool)
    stop_c = np.full(n, np.nan)
    alvo_c = np.full(n, np.nan)
    stop_v = np.full(n, np.nan)
    alvo_v = np.full(n, np.nan)

    for i in range(n):
        if np.isnan(range_high[i]) or np.isnan(range_low[i]) or np.isnan(cl[i]):
            continue
        if not volume_ok[i]:
            continue

        # filtro de corpo/pavio: forca o rompimento ter corpo e rejeicao controlada
        if filtro_corpo:
            if corpo[i] <= 0 or np.isnan(corpo[i]):
                continue

        # COMPRA: close acima do alto da faixa
        if cl[i] > range_high[i]:
            if filtro_corpo and wick_up[i] >= corpo[i] * max_wick_ratio:
                continue  # pavio superior grande = rejeicao; nao compra
            compra[i] = True
            stop_c[i] = range_low[i] - (atr[i] * atr_mult if stop_atr else 0)
            risco = max(cl[i] - stop_c[i], 1e-12)
            alvo_c[i] = cl[i] + rr * risco
        # VENDA: close abaixo do baixo da faixa
        elif cl[i] < range_low[i]:
            if filtro_corpo and wick_dn[i] >= corpo[i] * max_wick_ratio:
                continue  # pavio inferior grande = rejeicao; nao vende
            venda[i] = True
            stop_v[i] = range_high[i] + (atr[i] * atr_mult if stop_atr else 0)
            risco = max(stop_v[i] - cl[i], 1e-12)
            alvo_v[i] = cl[i] - rr * risco

    df["range_high"] = range_high
    df["range_low"] = range_low
    df["volume_ok"] = volume_ok
    df["entrada_compra"] = compra
    df["entrada_venda"] = venda
    df["stop_compra"] = stop_c
    df["alvo_compra"] = alvo_c
    df["stop_venda"] = stop_v
    df["alvo_venda"] = alvo_v

    # Filtros de direcao
    if filtro_macd:
        macd_c = _macd_ok(cl)
        df["macd_ok"] = macd_c
        # compra exige momentum comprador; venda exige momentum vendedor
        df["entrada_compra"] = df["entrada_compra"] & macd_c
        df["entrada_venda"] = df["entrada_venda"] & (~macd_c)

    if filtro_htf:
        df = aplicar_filtro_htf(df, htf_ema_period)

    if dias_operacao:
        if "abertura_tempo" in df.columns and len(df) > 0:
            dia = pd.to_datetime(df["abertura_tempo"]).dt.dayofweek.to_numpy()
            allowed = np.isin(dia, list(dias_operacao))
            df["entrada_compra"] = df["entrada_compra"] & allowed
            df["entrada_venda"] = df["entrada_venda"] & allowed

    return df


def aplicar_filtro_htf(df, htf_ema_period):
    """So aceita COMPRA em tendencia de alta (preco > EMA 1h) e VENDA em baixa."""
    df = df.copy()
    if "abertura_tempo" not in df.columns or len(df) == 0:
        return df
    idx = pd.to_datetime(df["abertura_tempo"])
    closes = df["close"].to_numpy(dtype=float)
    s = pd.Series(closes, index=idx)

    htf_ema = s.resample("1h").last().ewm(span=htf_ema_period, adjust=False).mean()
    htf_ema_m15 = htf_ema.reindex(idx, method="ffill").to_numpy()

    htf_alta = np.ones(len(df), dtype=bool)
    valid = ~np.isnan(htf_ema_m15)
    htf_alta[valid] = closes[valid] > htf_ema_m15[valid]

    df["htf_ema"] = htf_ema_m15
    df["htf_alta"] = htf_alta
    df["entrada_compra"] = df["entrada_compra"] & htf_alta
    df["entrada_venda"] = df["entrada_venda"] & (~htf_alta)
    return df
