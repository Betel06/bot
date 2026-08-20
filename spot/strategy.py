import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dados import buscar_historico
from core.indicadores import calcular_rsi, calcular_ema
from spot.config import STOP_PCT, ROI_TABELA, TAXA, USAR_FILTRO, PARES


TAXA_POR_LADO = TAXA
RISCO_POR_TRADE = 0.02


def tendencia(par, tf="1h"):
    try:
        df = buscar_historico(par, tf, 300)
        c = df["close"].astype(float)
        ema20 = calcular_ema(c, 20)
        ema50 = calcular_ema(c, 50)
        rsi = calcular_rsi(c)
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        r = float(rsi.iloc[-1])
        if e20 > e50 and r > 50:
            return "ALTA"
        elif e20 < e50 and r < 50:
            return "BAIXA"
    except Exception:
        pass
    return "NEUTRA"


def analisar(par):
    try:
        df = buscar_historico(par, "5m", 200)
        c = df["close"].astype(float)
        rsi = calcular_rsi(c)
        preco = float(c.iloc[-1])
        rsi_val = float(rsi.iloc[-1])

        if USAR_FILTRO:
            tend = tendencia(par, "15m")
        else:
            tend = "ALTA"

        sinal = None
        motivo = ""
        stop = None
        alvo = None

        if rsi_val < 40 and tend == "ALTA":
            sinal = "COMPRA"
            stop = preco * (1 - STOP_PCT)
            alvo = preco * (1 + ROI_TABELA[0])
            motivo = f"RSI {rsi_val:.1f} < 40"
            if USAR_FILTRO:
                motivo += f" + Tendencia {tend}"
        elif rsi_val > 70 and tend == "BAIXA":
            sinal = "VENDA"
            stop = preco * (1 + STOP_PCT)
            alvo = preco * (1 - ROI_TABELA[0])
            motivo = f"RSI {rsi_val:.1f} > 70"
            if USAR_FILTRO:
                motivo += f" + Tendencia {tend}"

        return {
            "par": par,
            "preco": preco,
            "sinal": sinal,
            "motivo": motivo,
            "stop": stop,
            "alvo": alvo,
            "rsi": rsi_val,
            "tendencia": tend,
        }
    except Exception as e:
        print(f"  Erro ao analisar {par}: {e}")
        return None


def backtest(par, saldo=500, intervalo="5m", candles=6000,
             stop_pct=None, roi_tabela=None, usar_filtro=None):
    if stop_pct is None:
        stop_pct = STOP_PCT
    if roi_tabela is None:
        roi_tabela = ROI_TABELA
    if usar_filtro is None:
        usar_filtro = USAR_FILTRO

    df_main = buscar_historico(par, intervalo, candles)

    if usar_filtro:
        if intervalo == "5m":
            df_filt = buscar_historico(par, "15m", candles)
        elif intervalo == "15m":
            df_filt = buscar_historico(par, "1h", candles)
        elif intervalo == "4h":
            df_filt = buscar_historico(par, "1d", candles)
        else:
            df_filt = None
    else:
        df_filt = None

    if df_main is None or len(df_main) < 200:
        return []
    if usar_filtro and (df_filt is None or len(df_filt) < 50):
        return []

    c = df_main["close"].astype(float)
    h = df_main["high"].astype(float)
    l = df_main["low"].astype(float)
    aberturas = df_main["abertura_tempo"].astype(float)
    rsi = calcular_rsi(c)

    if usar_filtro:
        c_f = df_filt["close"].astype(float)
        ema20_f = calcular_ema(c_f, 20)
        ema50_f = calcular_ema(c_f, 50)
        rsi_f = calcular_rsi(c_f)
        ab_f = df_filt["abertura_tempo"].astype(float)

    trades = []
    i = 50
    fim = -6

    while i < len(df_main) - 2 and saldo > 10:
        if i - fim < 6:
            i += 1; continue

        rsi_val = float(rsi.iloc[i])

        if usar_filtro:
            candle_time = float(aberturas.iloc[i])
            idx_f = ab_f.searchsorted(candle_time) - 1
            if idx_f < 50:
                i += 1; continue
            e20 = float(ema20_f.iloc[idx_f])
            e50 = float(ema50_f.iloc[idx_f])
            rf = float(rsi_f.iloc[idx_f])
            if e20 > e50 and rf > 50:
                tend = "ALTA"
            elif e20 < e50 and rf < 50:
                tend = "BAIXA"
            else:
                tend = "NEUTRA"
        else:
            tend = "ALTA"

        ent = stop = direcao = None

        if rsi_val < 40 and tend == "ALTA":
            ent = float(c.iloc[i+1])
            stop = ent * (1 - stop_pct)
            direcao = "COMPRA"
        elif rsi_val > 70 and tend == "BAIXA":
            ent = float(c.iloc[i+1])
            stop = ent * (1 + stop_pct)
            direcao = "VENDA"

        if ent is None:
            i += 1; continue

        risco_valor = saldo * RISCO_POR_TRADE
        stop_distancia = ent * stop_pct
        tamanho = risco_valor / stop_distancia
        fee_entrada = tamanho * ent * TAXA_POR_LADO

        res = None
        j = i + 2
        lim = min(i + 102, len(df_main))

        while j < lim:
            hj = float(h.iloc[j])
            lj = float(l.iloc[j])
            cj = float(c.iloc[j])
            ch = j - (i + 1)

            if direcao == "COMPRA":
                lc = (cj - ent) / ent
                lh = (hj - ent) / ent
                for t, roi in sorted(roi_tabela.items()):
                    if ch >= t and lc >= roi:
                        res = "ganho"; break
                if res: break
                if lh >= 0.08: res = "ganho"; break
                if lj <= stop: res = "perda"; break
            else:
                lc = (ent - cj) / ent
                ll = (ent - lj) / ent
                for t, roi in sorted(roi_tabela.items()):
                    if ch >= t and lc >= roi:
                        res = "ganho"; break
                if res: break
                if ll >= 0.08: res = "ganho"; break
                if hj >= stop: res = "perda"; break
            j += 1

        if res and j < len(df_main):
            cf = float(c.iloc[j])
            if direcao == "COMPRA":
                lp = (cf - ent) / ent
                if res == "perda" and cf < stop:
                    lp = (stop - ent) / ent
            else:
                lp = (ent - cf) / ent
                if res == "perda" and cf > stop:
                    lp = (ent - stop) / ent

            fee_saida = tamanho * ent * TAXA_POR_LADO
            lucro_reais = tamanho * ent * lp - fee_entrada - fee_saida
            lucro_reais = max(lucro_reais, -saldo)
            saldo += lucro_reais

            timestamp = float(aberturas.iloc[j])
            data = datetime.fromtimestamp(timestamp / 1000)

            trades.append({
                "par": par,
                "direcao": direcao,
                "resultado": res,
                "entrada": ent,
                "saida": cf,
                "lucro_pct": lp * 100,
                "lucro_reais": lucro_reais,
                "saldo": saldo,
                "rsi": rsi_val,
                "tendencia": tend,
                "data": data,
                "fee": fee_entrada + fee_saida,
            })

            fim = j
            i = j + 1
        else:
            i += 1

    return trades


def backtest_todos(saldo=500, intervalo=None, candles=6000,
                   stop_pct=None, roi_tabela=None, usar_filtro=None):
    if intervalo is None:
        from spot.config import INTERVALO
        intervalo = INTERVALO
    todos = []
    for par in PARES:
        trades = backtest(par, saldo, intervalo, candles,
                         stop_pct, roi_tabela, usar_filtro)
        todos.extend(trades)
        time.sleep(0.1)
    return todos


def imprimir(trades, titulo, saldo_inicial):
    if not trades:
        print(f"\n  {titulo}")
        print(f"  Nenhum trade encontrado.")
        return

    saldo_final = trades[-1]["saldo"]
    total = len(trades)
    ganhos = sum(1 for t in trades if t["resultado"] == "ganho")
    perdas = total - ganhos
    lucro = saldo_final - saldo_inicial
    wr = ganhos / total * 100

    ganho_medio = sum(t["lucro_reais"] for t in trades if t["resultado"] == "ganho") / ganhos if ganhos > 0 else 0
    perda_media = sum(t["lucro_reais"] for t in trades if t["resultado"] == "perda") / perdas if perdas > 0 else 0
    pf = (ganho_medio * ganhos) / abs(perda_media * perdas) if perdas > 0 and perda_media != 0 else float('inf')

    fees = sum(t.get("fee", 0) for t in trades)
    dd_max = 0
    pico = saldo_inicial
    for t in trades:
        if t["saldo"] > pico:
            pico = t["saldo"]
        dd = pico - t["saldo"]
        if dd > dd_max:
            dd_max = dd

    print(f"\n{'='*55}")
    print(f"  {titulo}")
    print(f"{'='*55}")
    print(f"  Capital:  R${saldo_inicial:.2f}")
    print(f"  Final:    R${saldo_final:.2f}")
    print(f"  Lucro:    R${lucro:+.2f} ({lucro/saldo_inicial*100:+.1f}%)")
    print(f"  Trades:   {total} ({ganhos}W / {perdas}L)")
    print(f"  Win:      {wr:.1f}%")
    print(f"  PF:       {pf:.2f}")
    print(f"  Ganho:    R${ganho_medio:+.2f} | Perda: R${perda_media:+.2f}")
    print(f"  Fees:     R${fees:.2f}")
    print(f"  DD:       R${dd_max:.2f}")
    print(f"{'='*55}")


def imprimir_resumo(trades, saldo_inicial):
    if not trades:
        print("  Nenhum trade.")
        return

    meses = {}
    for t in trades:
        mk = t["data"].strftime("%Y-%m")
        if mk not in meses:
            meses[mk] = {"t": 0, "w": 0, "lr": 0}
        meses[mk]["t"] += 1
        if t["resultado"] == "ganho":
            meses[mk]["w"] += 1
        meses[mk]["lr"] += t["lucro_reais"]

    saldo = saldo_inicial
    print()
    print("  {:12s} | {:>6s} | {:>5s} | {:>9s} | {:>9s} | {:>8s}".format(
        "Mes", "Trades", "Win%", "Lucro", "Saldo", "Retorno"))
    print("  " + "-" * 60)

    for mes in sorted(meses.keys()):
        d = meses[mes]
        wr = d["w"] / d["t"] * 100 if d["t"] > 0 else 0
        ret = d["lr"] / saldo * 100 if saldo > 0 else 0
        saldo += d["lr"]
        print("  {:12s} | {:6d} | {:5.1f}% | R${:+7.2f} | R${:7.2f} | {:+6.1f}%".format(
            mes, d["t"], wr, d["lr"], saldo, ret))

    lucro = saldo - saldo_inicial
    total = len(trades)
    ganhos = sum(1 for t in trades if t["resultado"] == "ganho")
    wr = ganhos / total * 100

    print("\n  Lucro total: R${:+.2f} ({:+.1f}%) | Win: {:.1f}% | {} trades".format(
        lucro, lucro/saldo_inicial*100, wr, total))

    por_par = {}
    for t in trades:
        p = t["par"]
        if p not in por_par:
            por_par[p] = {"t": 0, "w": 0, "lr": 0}
        por_par[p]["t"] += 1
        if t["resultado"] == "ganho":
            por_par[p]["w"] += 1
        por_par[p]["lr"] += t["lucro_reais"]

    print("\n  Ranking:")
    for par, d in sorted(por_par.items(), key=lambda x: x[1]["lr"], reverse=True):
        wrp = d["w"] / d["t"] * 100 if d["t"] > 0 else 0
        print("    {:14s} | {:3d} | {:5.1f}% | R${:+8.2f}".format(
            par, d["t"], wrp, d["lr"]))
