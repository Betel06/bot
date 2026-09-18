"""
monitor_m15.py - Bot de daytrade M15 (paper trading) - Breakout de range + volume.

REUTILIZA a mesma logica de sinais do backtest (m15/estrategia.py).
Rodado como paper trading: banco fake, posicoes simuladas, Telegram.

IMPORTANTE (leia antes de usar):
  Este bot so deve ser LIGADO depois que a estrategia for APROVADA no
  backtest (ver logs/backtest_m15.json e docs/m15_conclusao.md). Enquanto a
  deciso nao for tomada, mantenha FASE_PAPEL=True (padrao) e o bot apenas
  registra os sinais que teria gerado, sem sinalizar como se tivesse edge.

Uso:
  python m15/monitor_m15.py
"""

import sys
import os
import json
import time
import threading
import logging
import collections
from datetime import datetime, timezone, timedelta

import pandas as pd

BRT = timezone(timedelta(hours=-3))

import requests

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from m15 import config as cfg
from m15 import estrategia as strat
from core import dados

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
for _h in logging.getLogger().handlers:
    _h.formatter.converter = lambda *a: datetime.now(BRT).timetuple()

SECAO = "m15_bot"
FASE_PAPEL = True  # NAO mudar antes de aprovacao no backtest

# Banca fake (paper)
BANCO_INICIAL = cfg.BANCO_INICIAL
RISCO_POR_TRADE = cfg.RISCO_POR_TRADE


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
        "banca": BANCO_INICIAL, "banca_inicial": BANCO_INICIAL,
        "wins": 0, "losses": 0, "total_lucro": 0.0,
        "posicoes_abertas": {}, "historico": [],
        "ultimos_timestamps": {},
    }


def carregar_banca():
    dados = carregar_json(os.path.join(BOT_DIR, "logs", "m15_banca.json"), {})
    pad = _banca_padrao()
    pad.update({k: v for k, v in dados.items() if k in pad})
    return pad


def salvar_banca(b):
    salvar_json(os.path.join(BOT_DIR, "logs", "m15_banca.json"), b)


def enviar_telegram(mensagem):
    try:
        from futuro.telegram import enviar_mensagem
        enviar_mensagem(mensagem)
    except Exception:
        pass


def baixar_ultimas(par, limite=200):
    df = dados.buscar_candles(par, cfg.INTERVALO, limite, mercado="spot")
    df["abertura_tempo"] = pd.to_datetime(df["abertura_tempo"])
    df["abertura_tempo"] = df["abertura_tempo"].dt.tz_localize(None)
    return df.sort_values("abertura_tempo").reset_index(drop=True)


def ver_sinais_na_ultima_vela(df_sinais):
    """Retorna lista de sinais na(s) vela(s) mais recentes fechadas."""
    sinais = []
    n = len(df_sinais)
    # ultimas 2 velas fechadas (evita a vela atual ainda aberta)
    for i in range(max(0, n - 2), n):
        v = df_sinais.iloc[i]
        amp = "COMPRA" if bool(v["entrada_compra"]) else ("VENDA" if bool(v["entrada_venda"]) else None)
        if amp:
            sinais.append({
                "tempo": str(v["abertura_tempo"])[:19],
                "dir": amp,
                "close": float(v["close"]),
                "stop": float(v["stop_compra"]) if amp == "COMPRA" else float(v["stop_venda"]),
                "alvo": float(v["alvo_compra"]) if amp == "COMPRA" else float(v["alvo_venda"]),
            })
    return sinais


def monitor_loop():
    time.sleep(5)
    banca_data = carregar_banca()

    if FASE_PAPEL:
        logging.info("M15 BOT em FASE PAPEL (nao confirmado no backtest) - "
                     "apenas registrando sinais.")
        enviar_telegram(
            "🧪 BOT M15 em FASE PAPEL (avaliacao)\n"
            "Breakout range + volume - M15\n"
            f"Ativos: {', '.join(cfg.PARES)}\n"
            "⚠️  Ainda NAO aprovado no backtest. Nao considerar sinais como edge."
        )

    # cache das ultimas velas para so rodar 1x por ativo a cada loop
    ultimos_sinais_por_ativo = {}

    while True:
        try:
            for par in cfg.PARES:
                df = baixar_ultimas(par, limite=cfg.RANGE_LENGTH + 60)
                df_sinais = strat.calcular_sinais(
                    df, cfg.RANGE_LENGTH, cfg.VOL_MULTIPLIER, cfg.VOL_WINDOW,
                    cfg.RR, cfg.REQUER_FECHAMENTO, cfg.FILTRO_HTF, cfg.HTF_EMA_PERIOD,
                    filtro_corpo=cfg.FILTRO_CORPO, max_wick_ratio=cfg.MAX_WICK_RATIO,
                    filtro_macd=cfg.FILTRO_MACD, stop_atr=cfg.STOP_ATR,
                    atr_mult=cfg.ATR_MULT, atr_len=cfg.ATR_LEN)
                sinais = ver_sinais_na_ultima_vela(df_sinais)
                for s in sinais:
                    chave = f"{par}_{s['tempo']}_{s['dir']}"
                    if chave in ultimos_sinais_por_ativo:
                        continue
                    ultimos_sinais_por_ativo[chave] = True
                    # registra o sinal (guarda para posterior analise; em papel
                    # NAO abre posicao ate aprovacao)
                    logging.info(f"[SINAL][{par}] {s['dir']} @ {s['close']} "
                                 f"SL {s['stop']} TP {s['alvo']} ({s['tempo']})")
                    if not FASE_PAPEL:
                        enviar_telegram(
                            f"🧪 M15 {par} {s['dir']}\n"
                            f"Entrada {s['close']:.6f}\n"
                            f"Stop {s['stop']:.6f}\n"
                            f"Alvo {s['alvo']:.6f}"
                        )

                # limpar cache antigo (mais de 50 sinais)
                if len(ultimos_sinais_por_ativo) > 200:
                    # manter so as 100 ultimas chaves
                    itens = list(ultimos_sinais_por_ativo.items())
                    ultimos_sinais_por_ativo = dict(itens[-100:])

        except Exception as e:
            logging.error(f"Erro no monitor: {e}")

        time.sleep(cfg.INTERVALO_MONITOR if hasattr(cfg, "INTERVALO_MONITOR") else 60)


def criar_app():
    from flask import Flask
    app = Flask(__name__)

    @app.route("/")
    def home():
        return {"bot": "m15", "fase": "papel" if FASE_PAPEL else "operando",
                "banca": carregar_banca()["banca"]}

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        b = carregar_banca()
        win, loss = b["wins"], b["losses"]
        total = win + loss
        wr = (win / total * 100) if total else 0
        return {
            "bot": "m15_bot", "fase": "papel" if FASE_PAPEL else "operando",
            "estrategia": "Breakout range + volume M15",
            "status": "aguardando_aprovacao" if FASE_PAPEL else "online",
            "banca": b["banca"], "wins": win, "losses": loss, "win_rate": wr,
            "posicoes_abertas": len(b["posicoes_abertas"]),
            "historico": b["historico"][-5:],
        }

    port = int(os.environ.get("PORT", 5004))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    criar_app()
