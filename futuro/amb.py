import os

import numpy as np
import pandas as pd

# Stop na estrutura: swing mais recente confirmado (pivot_len velas de atraso).
SWING_PIVOT_LEN = int(os.environ.get("SMC_PIVOT_LEN", "5"))
RR_ESTRUTURA = 3.0  # alvo de referência (display); a SAIDA real é na virada do sinal

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
    DataFrame de OHLCV. Retorna o mesmo df com is_bull, sinal_compra,
    sinal_venda, entrada_compra, entrada_venda e as bandas.

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

    df["is_bull"] = pd.Series(is_bull, index=df.index)
    df["sinal_compra"] = pd.Series(sinal_compra, index=df.index)
    df["sinal_venda"] = pd.Series(sinal_venda, index=df.index)
    df["entrada_compra"] = df["sinal_compra"]
    df["entrada_venda"] = df["sinal_venda"]
    df["amr_line"] = amr_line
    df["upper_band"] = upper_band
    df["lower_band"] = lower_band
    return df


def calcular_stop_estrutura(df, pivot_len=SWING_PIVOT_LEN):
    """Ancora o stop na estrutura: compra = abaixo do ultimo fundo confirmado,
    venda = acima do ultimo topo confirmado. O alvo é só referência de R:R
    (a saída do bot passa a ser na virada do sinal, sem alvo fixo)."""
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)

    fundo = np.full(n, np.nan)
    topo = np.full(n, np.nan)
    conf_fundo = np.full(n, np.nan)
    conf_topo = np.full(n, np.nan)
    for i in range(pivot_len, n - pivot_len):
        if lo[i] == lo[i - pivot_len:i + pivot_len + 1].min():
            fundo[i] = lo[i]
        if hi[i] == hi[i - pivot_len:i + pivot_len + 1].max():
            topo[i] = hi[i]

    # confirma o pivot pivot_len velas depois (mesmo atraso do grafico)
    for i in range(n):
        k = i + pivot_len
        if k < n:
            conf_fundo[k] = fundo[i]
            conf_topo[k] = topo[i]

    # ultimo fundo/topo confirmado ATE a barra atual
    last_fundo = np.full(n, np.nan)
    last_topo = np.full(n, np.nan)
    lf = np.nan
    lt = np.nan
    for i in range(n):
        if not np.isnan(conf_fundo[i]):
            lf = conf_fundo[i]
        if not np.isnan(conf_topo[i]):
            lt = conf_topo[i]
        last_fundo[i] = lf
        last_topo[i] = lt

    # fallback quando ainda nao tem swing confirmado: min/max das ultimas velas
    roll_low = pd.Series(lo).rolling(pivot_len * 2, min_periods=1).min().to_numpy()
    roll_high = pd.Series(hi).rolling(pivot_len * 2, min_periods=1).max().to_numpy()
    last_fundo = np.where(np.isnan(last_fundo), roll_low, last_fundo)
    last_topo = np.where(np.isnan(last_topo), roll_high, last_topo)

    df["stop_compra"] = last_fundo
    df["stop_venda"] = last_topo
    df["alvo_compra"] = cl + (cl - df["stop_compra"]) * RR_ESTRUTURA
    df["alvo_venda"] = cl - (df["stop_venda"] - cl) * RR_ESTRUTURA
    return df