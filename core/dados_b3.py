"""
Candles da B3 (mini dolar WDO, mini indice WIN) via tvdatafeed (TradingView).
Mesmo contrato de saida de core/dados.py: DataFrame com colunas
open/high/low/close/volume ordenado do mais antigo pro mais recente.

Env vars opcionais:
    TV_USER / TV_PASS -> login TradingView gratuito (mais barras por request)
"""

import os
import logging

import pandas as pd

from tvDatafeed import TvDatafeed
from tvDatafeed.main import Interval


SIMBOLOS = {
    "WDO": ("BMFBOVESPA", "WDO1!"),
    "WIN": ("BMFBOVESPA", "WIN1!"),
    "DXY": ("TVC", "DXY"),
}

INTERVALOS = {
    "1m": Interval.in_1_minute,
    "5m": Interval.in_5_minute,
    "15m": Interval.in_15_minute,
    "60m": Interval.in_1_hour,
}

ULTIMA_FONTE_B3 = {"ok": None, "erro": None}

_TV = {"obj": None}


def _tv():
    if _TV["obj"] is None:
        usuario = os.environ.get("TV_USER") or None
        senha = os.environ.get("TV_PASS") or None
        _TV["obj"] = TvDatafeed(username=usuario, password=senha)
    return _TV["obj"]


def _resolver(ativo):
    chave = str(ativo).upper().strip()
    if chave in SIMBOLOS:
        return SIMBOLOS[chave]
    raise ValueError("ativo B3 desconhecido: {}".format(ativo))


def buscar_candles_b3(ativo="WDO", intervalo="5m", limite=60):
    """Retorna DataFrame open/high/low/close/volume com os ultimos candles."""
    exchange, simbolo = _resolver(ativo)
    iv = INTERVALOS.get(intervalo)
    if iv is None:
        raise ValueError("intervalo B3 nao suportado: {}".format(intervalo))

    df = _tv().get_hist(simbolo, exchange, interval=iv, n_bars=int(limite))
    if df is None or len(df) == 0:
        ULTIMA_FONTE_B3["ok"] = False
        ULTIMA_FONTE_B3["erro"] = "sem dados do TradingView"
        raise ValueError("sem candles para {} {}".format(ativo, intervalo))

    df = df.reset_index()
    saida = pd.DataFrame({
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
        "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0),
        "abertura_tempo": df["datetime"],
    })
    saida = saida.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    ULTIMA_FONTE_B3["ok"] = True
    ULTIMA_FONTE_B3["erro"] = None
    return saida


def buscar_historico_b3(ativo, intervalo, total_candles):
    df = buscar_candles_b3(ativo, intervalo, min(int(total_candles), 5000))
    if len(df) == 0:
        raise ValueError("Nenhum candle encontrado para {} ({})".format(ativo, intervalo))
    return df
