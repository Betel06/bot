"""
Analytics - Analise de Performance, Backtest Avancado, Strategy vs Buy-and-Hold

Baseado no video MASTER AI Trading:
- Comparar estrategia vs buy-and-hold
- Analise de win rate por dia da semana
- Max drawdown analysis
- Sharpe ratio simplificado
- Expectancia matematica
"""
import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def calcular_buy_and_hold(par, intervalo="5m", candles=6000, capital_inicial=500):
    """
    Calcula retorno de buy-and-hold puro (compra tudo no inicio, segura).

    Returns:
        dict com retorno, preco_inicio, preco_fim, holding_pct, etc.
    """
    from core.dados import buscar_historico

    df = buscar_historico(par, intervalo, candles)
    c = df["close"].astype(float)
    aberturas = df["abertura_tempo"].astype(float)

    preco_inicio = float(c.iloc[0])
    preco_fim = float(c.iloc[-1])

    qtd = capital_inicial / preco_inicio
    valor_final = qtd * preco_fim

    taxa = 0.001
    custo_entrada = capital_inicial * taxa
    custo_saida = valor_final * taxa
    lucro_liquido = valor_final - capital_inicial - custo_entrada - custo_saida

    data_inicio = datetime.fromtimestamp(float(aberturas.iloc[0]) / 1000)
    data_fim = datetime.fromtimestamp(float(aberturas.iloc[-1]) / 1000)
    dias = (data_fim - data_inicio).days

    max_dd = 0
    pico = preco_inicio
    for preco in c:
        p = float(preco)
        if p > pico:
            pico = p
        dd = (pico - p) / pico
        if dd > max_dd:
            max_dd = dd

    return {
        "par": par,
        "preco_inicio": round(preco_inicio, 4),
        "preco_fim": round(preco_fim, 4),
        "capital_inicial": capital_inicial,
        "capital_final": round(valor_final, 2),
        "lucro_liquido": round(lucro_liquido, 2),
        "retorno_pct": round((valor_final / capital_inicial - 1) * 100, 1),
        "retorno_anualizado": round(
            ((valor_final / capital_inicial) ** (365 / max(dias, 1)) - 1) * 100, 1
        ),
        "max_dd_pct": round(max_dd * 100, 1),
        "dias": dias,
        "data_inicio": data_inicio.strftime("%d/%m/%Y"),
        "data_fim": data_fim.strftime("%d/%m/%Y"),
    }


def analisar_trades(trades, capital_inicial=500):
    """
    Analise completa de uma lista de trades.

    Returns:
        dict com metricas detalhadas
    """
    if not trades:
        return {"erro": "Nenhum trade"}

    total = len(trades)
    ganhos = [t for t in trades if t["resultado"] == "ganho"]
    perdas = [t for t in trades if t["resultado"] == "perda"]
    n_ganhos = len(ganhos)
    n_perdas = len(perdas)
    win_rate = n_ganhos / total * 100

    lucros_ganho = [t["lucro_reais"] for t in ganhos]
    lucros_perda = [t["lucro_reais"] for t in perdas]

    ganho_medio = sum(lucros_ganho) / n_ganhos if n_ganhos > 0 else 0
    perda_media = sum(lucros_perda) / n_perdas if n_perdas > 0 else 0

    pf_denom = abs(perda_media * n_perdas)
    profit_factor = (ganho_medio * n_ganhos) / pf_denom if pf_denom > 0 else float('inf')

    saldo_final = trades[-1]["saldo"]
    lucro_total = saldo_final - capital_inicial
    retorno_pct = (saldo_final / capital_inicial - 1) * 100

    max_dd = 0
    pico = capital_inicial
    dd_atual = 0
    for t in trades:
        if t["saldo"] > pico:
            pico = t["saldo"]
        dd = (pico - t["saldo"]) / pico
        if dd > max_dd:
            max_dd = dd
            dd_atual = dd * 100

    expectancia = (win_rate / 100 * ganho_medio) + ((1 - win_rate / 100) * perda_media)

    lucro_bruto_ganhos = sum(lucros_ganho)
    lucro_bruto_perdas = sum(lucros_perda)
    avg_win_pct = (lucro_bruto_ganhos / capital_inicial) / n_ganhos * 100 if n_ganhos > 0 else 0
    avg_loss_pct = (lucro_bruto_perdas / capital_inicial) / n_perdas * 100 if n_perdas > 0 else 0

    return {
        "total_trades": total,
        "ganhos": n_ganhos,
        "perdas": n_perdas,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "ganho_medio_usd": round(ganho_medio, 2),
        "perda_media_usd": round(perda_media, 2),
        "ganho_medio_pct": round(avg_win_pct, 1),
        "perda_media_pct": round(avg_loss_pct, 1),
        "expectancia_usd": round(expectancia, 4),
        "capital_inicial": capital_inicial,
        "capital_final": round(saldo_final, 2),
        "lucro_total": round(lucro_total, 2),
        "retorno_pct": round(retorno_pct, 1),
        "max_dd_pct": round(max_dd * 100, 1),
        "total_fees": round(sum(t.get("fee", 0) for t in trades), 2),
    }


def win_rate_por_dia(trades):
    """Win rate separado por dia da semana."""
    dias_pt = {
        0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui",
        4: "Sex", 5: "Sab", 6: "Dom"
    }

    stats = defaultdict(lambda: {"t": 0, "w": 0, "lr": 0})

    for t in trades:
        data = t.get("data")
        if isinstance(data, datetime):
            dia = data.weekday()
        else:
            continue

        stats[dia]["t"] += 1
        if t["resultado"] == "ganho":
            stats[dia]["w"] += 1
        stats[dia]["lr"] += t["lucro_reais"]

    resultado = {}
    for dia_num in range(7):
        s = stats[dia_num]
        wr = s["w"] / s["t"] * 100 if s["t"] > 0 else 0
        resultado[dias_pt[dia_num]] = {
            "trades": s["t"],
            "wins": s["w"],
            "losses": s["t"] - s["w"],
            "win_rate": round(wr, 1),
            "lucro": round(s["lr"], 2),
        }

    return resultado


def win_rate_por_hora(trades):
    """Win rate separado por hora do dia."""
    stats = defaultdict(lambda: {"t": 0, "w": 0, "lr": 0})

    for t in trades:
        data = t.get("data")
        if isinstance(data, datetime):
            hora = data.hour
        else:
            continue

        stats[hora]["t"] += 1
        if t["resultado"] == "ganho":
            stats[hora]["w"] += 1
        stats[hora]["lr"] += t["lucro_reais"]

    resultado = {}
    for hora in range(24):
        s = stats[hora]
        wr = s["w"] / s["t"] * 100 if s["t"] > 0 else 0
        resultado[f"{hora:02d}h"] = {
            "trades": s["t"],
            "wins": s["w"],
            "losses": s["t"] - s["w"],
            "win_rate": round(wr, 1),
            "lucro": round(s["lr"], 2),
        }

    return resultado


def sequencias(trades):
    """Analise de sequencias consecutivas."""
    max_win_streak = 0
    max_loss_streak = 0
    win_streak = 0
    loss_streak = 0

    for t in trades:
        if t["resultado"] == "ganho":
            win_streak += 1
            loss_streak = 0
        else:
            loss_streak += 1
            win_streak = 0

        max_win_streak = max(max_win_streak, win_streak)
        max_loss_streak = max(max_loss_streak, loss_streak)

    return {
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
    }


def comparar_compra_e_segurar(trades, par, intervalo="5m",
                               candles=6000, capital_inicial=500):
    """
    Compara performance da estrategia vs buy-and-hold.
    Exatamente como no video.
    """
    strat = analisar_trades(trades, capital_inicial)
    bh = calcular_buy_and_hold(par, intervalo, candles, capital_inicial)

    venceu = strat["retorno_pct"] > bh["retorno_pct"]

    return {
        "estrategia": {
            "retorno_pct": strat["retorno_pct"],
            "lucro_usd": strat["lucro_total"],
            "max_dd_pct": strat["max_dd_pct"],
            "trades": strat["total_trades"],
            "win_rate": strat["win_rate"],
            "capital_final": strat["capital_final"],
        },
        "buy_and_hold": {
            "retorno_pct": bh["retorno_pct"],
            "lucro_usd": bh["lucro_liquido"],
            "max_dd_pct": bh["max_dd_pct"],
            "capital_final": bh["capital_final"],
        },
        "venceu_estrategia": venceu,
        "multiplicador": round(
            strat["capital_final"] / bh["capital_final"], 2
        ) if bh["capital_final"] > 0 else 0,
    }


def imprimir_analise_completa(trades, par, capital_inicial=500):
    """Imprime relatorio completo de analise."""
    metrics = analisar_trades(trades, capital_inicial)
    dias = win_rate_por_dia(trades)
    horas = win_rate_por_hora(trades)
    seq = sequencias(trades)

    print(f"\n{'='*60}")
    print(f"  RELATORIO DE PERFORMANCE - {par}")
    print(f"{'='*60}")

    print(f"\n  RESUMO GERAL:")
    print(f"  Capital:     R${capital_inicial:.2f} -> R${metrics['capital_final']:.2f}")
    print(f"  Lucro:       R${metrics['lucro_total']:+.2f} ({metrics['retorno_pct']:+.1f}%)")
    print(f"  Trades:      {metrics['total_trades']} ({metrics['ganhos']}W / {metrics['perdas']}L)")
    print(f"  Win Rate:    {metrics['win_rate']:.1f}%")
    print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"  Expectancia: R${metrics['expectancia_usd']:.4f}/trade")
    print(f"  Fees Total:  R${metrics['total_fees']:.2f}")

    print(f"\n  RISCO:")
    print(f"  Max Drawdown: {metrics['max_dd_pct']:.1f}%")
    print(f"  Ganho medio:  R${metrics['ganho_medio_usd']:+.2f} ({metrics['ganho_medio_pct']:+.1f}%)")
    print(f"  Perda media:  R${metrics['perda_media_usd']:+.2f} ({metrics['perda_media_pct']:+.1f}%)")

    print(f"\n  SEQUENCIAS:")
    print(f"  Max win streak:  {seq['max_win_streak']}")
    print(f"  Max loss streak: {seq['max_loss_streak']}")

    print(f"\n  WIN RATE POR DIA DA SEMANA:")
    print(f"  {'Dia':<6} | {'Trades':>6} | {'Win%':>6} | {'Lucro':>10}")
    print(f"  {'-'*38}")
    for dia, s in dias.items():
        if s["trades"] > 0:
            print(f"  {dia:<6} | {s['trades']:>6} | {s['win_rate']:>5.1f}% | R${s['lucro']:>+8.2f}")

    print(f"\n  WIN RATE POR HORA (horas com trades):")
    print(f"  {'Hora':<6} | {'Trades':>6} | {'Win%':>6} | {'Lucro':>10}")
    print(f"  {'-'*38}")
    for hora, s in horas.items():
        if s["trades"] > 0:
            print(f"  {hora:<6} | {s['trades']:>6} | {s['win_rate']:>5.1f}% | R${s['lucro']:>+8.2f}")

    print(f"\n{'='*60}")


def imprimir_comparacao_bh(trades, par, intervalo="5m",
                            candles=6000, capital_inicial=500):
    """Imprime comparacao estrategia vs buy-and-hold."""
    comp = comparar_compra_e_segurar(
        trades, par, intervalo, candles, capital_inicial
    )

    s = comp["estrategia"]
    b = comp["buy_and_hold"]

    print(f"\n{'='*60}")
    print(f"  ESTRATEGIA vs BUY-AND-HOLD - {par}")
    print(f"{'='*60}")

    print(f"\n  {'Metrica':<25} | {'Estrategia':>12} | {'Buy&Hold':>12}")
    print(f"  {'-'*55}")
    print(f"  {'Capital Final':<25} | R${s['capital_final']:>9.2f} | R${b['capital_final']:>9.2f}")
    print(f"  {'Retorno':<25} | {s['retorno_pct']:>+10.1f}% | {b['retorno_pct']:>+10.1f}%")
    print(f"  {'Lucro USD':<25} | R${s['lucro_usd']:>+9.2f} | R${b['lucro_usd']:>+9.2f}")
    print(f"  {'Max Drawdown':<25} | {s['max_dd_pct']:>10.1f}% | {b['max_dd_pct']:>10.1f}%")
    print(f"  {'Win Rate':<25} | {s['win_rate']:>10.1f}% | {'N/A':>12}")

    print(f"\n  RESULTADO: ", end="")
    if comp["venceu_estrategia"]:
        print(f"ESTRATEGIA VENCEU por {comp['multiplicador']}x!")
        print(f"  A estrategia rendeu {s['retorno_pct']:+.1f}% vs {b['retorno_pct']:+.1f}% do buy-and-hold")
    else:
        print(f"BUY-AND-HOLD VENCEU!")
        print(f"  O buy-and-hold rendeu {b['retorno_pct']:+.1f}% vs {s['retorno_pct']:+.1f}% da estrategia")
        print(f"  Manter segurando seria {1/comp['multiplicador']:.1f}x melhor")

    print(f"\n  INSIGHT: ", end="")
    if s['max_dd_pct'] > b['max_dd_pct']:
        print(f"A estrategia tem MAIOR drawdown ({s['max_dd_pct']:.1f}%) que buy-and-hold ({b['max_dd_pct']:.1f}%)")
    else:
        print(f"A estrategia tem MENOR drawdown ({s['max_dd_pct']:.1f}%) que buy-and-hold ({b['max_dd_pct']:.1f}%)")

    print(f"\n{'='*60}")
