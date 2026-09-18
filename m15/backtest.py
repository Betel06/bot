"""
backtest.py - Engine de backtest do bot M15 (Breakout de range + volume).

Baixa dados reais (Binance via core/dados.buscar_historico), roda a estrategia
e mede edge de forma HONESTA:
  - inclui fees + slippage por ida e volta (COST_PCT)
  - uma posicao por vez por ativo
  - resultados por DIA DA SEMANA (o estudo que o usuario queria)
  - curvas de capital com risco % de banca

USO:
  python m15/backtest.py                       # rodar padrao
  python m15/backtest.py --pars BTCUSDT ETHUSDT --anos 3 --rr 3
  python m15/backtest.py --no-htf              # desliga filtro de tendencia
  python m15/backtest.py --salvar              # grava resultados em logs/
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from m15 import config as cfg
from m15 import estrategia as strat
from core import dados

BRT = timezone(timedelta(hours=-3))


# ---------------------------------------------------------------------------
# Simulacao de execucao (uma posicao por vez por ativo, com custo real)
# ---------------------------------------------------------------------------

def simular_trades(df, rr, cost_pct, risco_pct, banca, verbose_trades=False):
    """Simula posicoes de um ativo sobre o df ja com sinais, mantendo
    UMA posicao por vez (como o bot real opera). O sinal mais recente de
    compra OU venda abre posicao; apos fechar, espera novo sinal.

    Retorna (lista de resultados, serie de banca).
    """
    history = []
    posicao_aberta = False
    p_entrada = p_stop = p_alvo = p_dir = 0.0
    banca_atual = float(banca)
    curvas = []

    n = len(df)
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    aberturas = pd.to_datetime(df["abertura_tempo"]).reset_index(drop=True)

    entrada_c = df["entrada_compra"].to_numpy(dtype=bool)
    entrada_v = df["entrada_venda"].to_numpy(dtype=bool)
    stop_c = df["stop_compra"].to_numpy(dtype=float)
    alvo_c = df["alvo_compra"].to_numpy(dtype=float)
    stop_v = df["stop_venda"].to_numpy(dtype=float)
    alvo_v = df["alvo_venda"].to_numpy(dtype=float)

    for i in range(n):
        l = lows[i]; h = highs[i]

        if posicao_aberta:
            touched_sl = False
            touched_tp = False
            if p_dir == 1:  # compra
                if l <= p_stop:
                    touched_sl = True
                if h >= p_alvo:
                    touched_tp = True
            else:           # venda
                if h >= p_stop:
                    touched_sl = True
                if l <= p_alvo:
                    touched_tp = True

            # se tocou stop e alvo na mesma vela: assume o pior (stop)
            if touched_sl:
                preco_saida, motivo = p_stop, "SL"
            elif touched_tp:
                preco_saida, motivo = p_alvo, "TP"
            else:
                preco_saida, motivo = None, None

            if preco_saida is not None:
                pnl_pct = ((preco_saida - p_entrada) / p_entrada
                           if p_dir == 1 else
                           (p_entrada - preco_saida) / p_entrada)
                pnl_pct -= cost_pct / 100.0
                # risco em % da banca aplicado ao risco da operacao
                risco_frac = abs(p_entrada - p_stop) / p_entrada
                pnl_usd = (banca_atual * risco_pct *
                           (pnl_pct / risco_frac if risco_frac else 0))
                banca_atual += pnl_usd
                history.append({
                    "dir": ("COMPRA" if p_dir == 1 else "VENDA"),
                    "entrada": p_entrada, "stop": p_stop, "alvo": p_alvo,
                    "saida": preco_saida, "motivo": motivo,
                    "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                    "banca": banca_atual, "tempo": aberturas[i],
                })
                posicao_aberta = False
                if verbose_trades:
                    print(f"   -> {history[-1]['dir']} {motivo} "
                          f"{pnl_usd:.4f} @ {str(aberturas[i])[:19]}")

        if not posicao_aberta:
            if entrada_c[i] and not np.isnan(stop_c[i]):
                posicao_aberta = True
                p_entrada = closes[i]
                p_stop = stop_c[i]
                p_alvo = alvo_c[i]
                p_dir = 1
            elif entrada_v[i] and not np.isnan(stop_v[i]):
                posicao_aberta = True
                p_entrada = closes[i]
                p_stop = stop_v[i]
                p_alvo = alvo_v[i]
                p_dir = -1

        curvas.append(banca_atual)

    return history, curvas


# ---------------------------------------------------------------------------
# Analise por dia da semana
# ---------------------------------------------------------------------------

def analise_dia_semana(hist_pras):
    """historys de todos ativos -> estatisticas por dia da semana."""
    linhas = []
    for _, h in hist_pras:
        for r in h:
            dt = r["tempo"]
            # data de saida (dia em que o trade fechou)
            if hasattr(dt, "to_pydatetime"):
                dt = dt.to_pydatetime()
            weekday = dt.weekday()
            linhas.append({"weekday": weekday, "pnl": r["pnl_usd"],
                           "win": r["pnl_usd"] >= 0})
    if not linhas:
        return None
    dfw = pd.DataFrame(linhas)
    nomes = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    rows = []
    for d in range(7):
        sub = dfw[dfw["weekday"] == d]
        if len(sub) == 0:
            continue
        wins = int(sub["win"].sum())
        total = len(sub)
        rows.append({
            "dia": nomes[d],
            "trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total * 100, 1),
            "pnl_usd": round(sub["pnl"].sum(), 4),
            "pnl_medio": round(sub["pnl"].mean(), 4),
        })
    return rows


# ---------------------------------------------------------------------------
# Entrada de dados + execucao
# ---------------------------------------------------------------------------

def baixar_dados(par, intervalo, anos):
    """Baixa anos de historia M15 (grantes de velas)."""
    dias = int(anos * 365.25)
    # M15 = 96 velas/dia
    total = dias * 96
    df = dados.buscar_historico(par, intervalo, total, mercado="spot")
    df["abertura_tempo"] = pd.to_datetime(df["abertura_tempo"], unit="ms")
    df["abertura_tempo"] = df["abertura_tempo"].dt.tz_localize(None)
    # ordenar e deduplicar
    df = df.sort_values("abertura_tempo").drop_duplicates("abertura_tempo").reset_index(drop=True)
    return df


def rodar(par, anos=None, rr=None, cost=None, filtro_htf=True, banca=None,
          risco=None, verbose=True):
    if anos is None:
        anos = cfg.ANOS_BACKTEST
    if rr is None:
        rr = cfg.RR
    if cost is None:
        cost = cfg.COST_PCT
    if banca is None:
        banca = cfg.BANCO_INICIAL
    if risco is None:
        risco = cfg.RISCO_POR_TRADE

    if verbose:
        print(f"\n==> {par} | {cfg.INTERVALO} | {anos} anos | RR 1:{rr} | "
              f"cost {cost}% | filtroHTF {filtro_htf}")

    df = baixar_dados(par, cfg.INTERVALO, anos)
    df_sinais = strat.calcular_sinais(
        df, cfg.RANGE_LENGTH, cfg.VOL_MULTIPLIER, cfg.VOL_WINDOW,
        rr, cfg.REQUER_FECHAMENTO, filtro_htf, cfg.HTF_EMA_PERIOD,
        filtro_corpo=cfg.FILTRO_CORPO, max_wick_ratio=cfg.MAX_WICK_RATIO,
        filtro_macd=cfg.FILTRO_MACD, stop_atr=cfg.STOP_ATR,
        atr_mult=cfg.ATR_MULT, atr_len=cfg.ATR_LEN)

    n_sinais = int(df_sinais["entrada_compra"].sum() +
                   df_sinais["entrada_venda"].sum())
    if verbose:
        print(f"   dados: {len(df_sinais)} velas | sinais: {n_sinais} "
              f"(C {int(df_sinais['entrada_compra'].sum())} / "
              f"V {int(df_sinais['entrada_venda'].sum())})")

    trade_c, _curva_c = simular_trades(df_sinais, rr, cost, risco, banca)
    # direcao fica marcada dentro de cada trade; nao separamos mais C/V
    trades = trade_c  # ja contem ambos (COMPRA e VENDA) numa unica passada
    trades.sort(key=lambda x: x["tempo"])

    # curva combinada (reescala pelo numero de trades de cada lado)
    # simplificacao: soma os PnLs em ordem cronologica sobre a banca inicial
    banca = float(banca)
    banca_series = [banca]
    for t in trades:
        banca += t["pnl_usd"]
        t["banca"] = banca
        banca_series.append(banca)

    # estatisticas
    n_tr = len(trades)
    wins = sum(1 for t in trades if t["pnl_usd"] >= 0)
    losses = n_tr - wins
    wr = (wins / n_tr * 100) if n_tr else 0
    soma = sum(t["pnl_usd"] for t in trades)
    g = [t for t in trades if t["pnl_usd"] > 0]
    l = [t for t in trades if t["pnl_usd"] < 0]
    avg_win = (sum(t["pnl_usd"] for t in g) / len(g)) if g else 0
    avg_loss = (sum(t["pnl_usd"] for t in l) / len(l)) if l else 0
    profit_factor = (sum(t["pnl_usd"] for t in g) /
                     abs(sum(t["pnl_usd"] for t in l))) if l else float("inf")

    # max drawdown da curva
    peak = banca_series[0]
    mdd = 0.0
    for v in banca_series:
        peak = max(peak, v)
        dd = (peak - v)
        if dd > mdd:
            mdd = dd

    # resultados por direcao
    res = {
        "par": par, "intervalo": cfg.INTERVALO, "rr": rr, "cost_pct": cost,
        "filtro_htf": filtro_htf, "anos": anos,
        "trades": n_tr, "wins": wins, "losses": losses, "win_rate": round(wr, 1),
        "pnl_usd": round(soma, 4), "pnl_pct_banca": round(soma / cfg.BANCO_INICIAL * 100, 2),
        "expectancy_usd": round(soma / n_tr, 4) if n_tr else 0,
        "avg_win": round(avg_win, 4), "avg_loss": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_usd": round(mdd, 4),
        "win_que": round(wr and (avg_win / -avg_loss if avg_loss else float("inf")), 2),
        "trades_c": sum(1 for t in trades if t["dir"] == "COMPRA"),
        "trades_v": sum(1 for t in trades if t["dir"] == "VENDA"),
    }
    return res, df_sinais, trades


def main():
    p = argparse.ArgumentParser(description="Backtest bot M15 breakout")
    p.add_argument("--pars", nargs="*", default=cfg.PARES)
    p.add_argument("--anos", type=float, default=cfg.ANOS_BACKTEST)
    p.add_argument("--rr", type=float, default=cfg.RR)
    p.add_argument("--cost", type=float, default=cfg.COST_PCT)
    p.add_argument("--no-htf", action="store_true")
    p.add_argument("--salvar", action="store_true")
    args = p.parse_args()

    total_trades = 0
    all_res = []
    all_history = []
    total_pnl = 0.0

    for par in args.pars:
        try:
            res, df_s, trades = rodar(par, args.anos, args.rr, args.cost,
                                      not args.no_htf)
        except Exception as e:
            print(f"ERRO em {par}: {e}")
            continue
        all_res.append(res)
        all_history.append((par, trades))
        total_trades += res["trades"]
        total_pnl += res["pnl_usd"]

        # impressao resumo
        print(f"   trades={res['trades']} win_rate={res['win_rate']}% "
              f"pnl={res['pnl_usd']:.2f} PF={res['profit_factor']} "
              f"expect={res['expectancy_usd']:.4f} "
              f"MDD={res['max_drawdown_usd']:.2f}")

    # agregado
    wins = sum(r["wins"] for r in all_res)
    losses = sum(r["losses"] for r in all_res)
    n_all = wins + losses
    wr_all = (wins / n_all * 100) if n_all else 0
    print("\n" + "=" * 60)
    print(f"AGREGADO ({len(all_res)} ativos, {args.anos} anos)")
    print(f"  trades: {n_all} | win_rate: {wr_all:.1f}% | "
          f"pnl: {total_pnl:.2f} USDT")
    print("=" * 60)

    if n_all == 0:
        print("Nenhum trade gerado. Ajuste parametros.")
        return

    # por dia da semana
    print("\n=== STATS POR DIA DA SEMANA ===")
    dia_stats = analise_dia_semana(all_history)
    if dia_stats:
        for r in dia_stats:
            print(f"  {r['dia']}: {r['trades']} trades | WR {r['win_rate']}% "
                  f"| pnl {r['pnl_usd']:.2f} | medio {r['pnl_medio']:.4f}")

    if args.salvar:
        logs_dir = os.path.join(BOT_DIR, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        out = {
            "gerado_em": datetime.now(BRT).strftime("%Y-%m-%d %H:%M"),
            "parametros": {
                "intervalo": cfg.INTERVALO, "range_length": cfg.RANGE_LENGTH,
                "vol_mult": cfg.VOL_MULTIPLIER, "vol_window": cfg.VOL_WINDOW,
                "rr": args.rr, "cost_pct": args.cost, "anos": args.anos,
                "filtro_htf": not args.no_htf,
            },
            "agregado": {"trades": n_all, "wr": wr_all, "pnl": total_pnl},
            "por_ativo": all_res,
            "por_dia_semana": dia_stats,
        }
        caminho = os.path.join(logs_dir, "backtest_m15.json")
        with open(caminho, "w") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"\nResultados salvos em {caminho}")


if __name__ == "__main__":
    main()
