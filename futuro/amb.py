import numpy as np
import pandas as pd

ESE_RATIO = 3.0  # R:R alvo/stop (risco = 1 ATR, alvo = 3 ATR)

# ── Parametros padrao (iguais ao Pine amb_v2_pt.pine) ────────────────
BASE_LEN = 8
ATR_LEN = 7
BAND_SMOOTH = 8
UPPER_MULT = 1.5
LOWER_MULT = 1.5
ADAPT_LEN = 14
FAST_SMOOTH = 2
SLOW_SMOOTH = 10


def _ema(serie, comprimento):
    return serie.ewm(span=comprimento, adjust=False).mean()


def _atr(high, low, close, comprimento):
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return _ema(tr, comprimento)


def calcular_amb(df):
    """Aplica a logica do indicador AMB v2 (© Uptrick, CC BY-SA 4.0) em um
    DataFrame de OHLCV (colunas high/low/close/volume). Retorna o mesmo df com:

      is_bull / sinal_compra / sinal_venda / entrada_compra / entrada_venda
      stop_compra / alvo_compra / stop_venda / alvo_venda
      amr_line / upper_band / lower_band

    A entrada (Compra/Venda) e a virada confirmada da tendencia, igual ao
    sinal 'ENTRADA COMPRA/VENDA (AMB)' do Pine.
    """
    df = df.copy()
    n = len(df)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    # ── velocidade adaptativa ──
    direction = (close - close.shift(ADAPT_LEN)).abs()
    noise = close.diff().abs().rolling(ADAPT_LEN).sum()
    er = direction / noise.replace(0, np.nan)
    er = er.fillna(0.0)

    fast_sc = 2.0 / (FAST_SMOOTH + 1)
    slow_sc = 2.0 / (SLOW_SMOOTH + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

    # ── linha base adaptativa (recursiva, igual ao var do Pine) ──
    ama1 = np.empty(n)
    prev = None
    for i in range(n):
        c = float(close.iloc[i])
        if prev is None:
            prev = c
        else:
            prev = prev + float(sc.iloc[i]) * (c - prev)
        ama1[i] = prev
    ama1 = pd.Series(ama1, index=df.index)

    ama2 = _ema(ama1, max(2, round(BASE_LEN * 0.5)))
    amr_line = _ema(ama2, 2)

    # ── bandas suavizadas ──
    atr_suave = _ema(_atr(high, low, close, ATR_LEN), BAND_SMOOTH)
    atr_norm = _ema(atr_suave, ATR_LEN)
    vol_ratio = atr_suave / atr_norm.replace(0, np.nan)

    dyn_mult_up = UPPER_MULT * vol_ratio.clip(lower=0.5, upper=1.8)
    dyn_mult_dn = LOWER_MULT * vol_ratio.clip(lower=0.5, upper=1.8)

    upper_band = _ema(amr_line + dyn_mult_up * atr_suave, BAND_SMOOTH)
    lower_band = _ema(amr_line - dyn_mult_dn * atr_suave, BAND_SMOOTH)

    # ── estado da tendencia (isBull, travado: nunca neutro) ──
    is_bull = np.ones(n, dtype=bool)
    for i in range(1, n):
        c = float(close.iloc[i])
        if not np.isnan(upper_band.iloc[i]) and c > upper_band.iloc[i]:
            is_bull[i] = True
        elif not np.isnan(lower_band.iloc[i]) and c < lower_band.iloc[i]:
            is_bull[i] = False
        else:
            is_bull[i] = is_bull[i - 1]

    # ── sinais de entrada: virada confirmada (lastState != prevState) ──
    estado = np.where(is_bull, 1, -1)
    sinal_compra = np.zeros(n, dtype=bool)
    sinal_venda = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if estado[i] == 1 and estado[i - 1] == -1:
            sinal_compra[i] = True
        elif estado[i] == -1 and estado[i - 1] == 1:
            sinal_venda[i] = True

    # ── stop/alvo ATR-based (risco 1 ATR, alvo 3 ATR) ──
    atr_ref = atr_suave.bfill()

    df["is_bull"] = pd.Series(is_bull, index=df.index)
    df["sinal_compra"] = pd.Series(sinal_compra, index=df.index)
    df["sinal_venda"] = pd.Series(sinal_venda, index=df.index)
    df["entrada_compra"] = df["sinal_compra"]
    df["entrada_venda"] = df["sinal_venda"]
    df["amr_line"] = amr_line
    df["upper_band"] = upper_band
    df["lower_band"] = lower_band
    df["stop_compra"] = close - atr_ref
    df["alvo_compra"] = close + atr_ref * ESE_RATIO
    df["stop_venda"] = close + atr_ref
    df["alvo_venda"] = close - atr_ref * ESE_RATIO
    return df