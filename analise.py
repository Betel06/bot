"""
Relatorio de Analise - Risk Management + Backtest + Comparacao
Execute: python analise.py [--par ATOMUSDT] [--saldo 500] [--candles 6000]
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spot.strategy import backtest, backtest_todos
from spot.config import PARES, STOP_PCT, ROI_TABELA, TAXA, USAR_FILTRO
from core.risk_manager import (
    calcular_tamanho_posicao,
    kelly_criterion,
    calcular_rr,
    avaliar_trade,
    max_drawdown_protection,
)
from core.analytics import (
    imprimir_analise_completa,
    imprimir_comparacao_bh,
    analisar_trades,
    comparar_compra_e_segurar,
)


def relatorio_risk_management():
    """Demonstra calculadora de position sizing."""
    print("\n" + "=" * 60)
    print("  RISK MANAGEMENT - POSITION SIZING CALCULATOR")
    print("=" * 60)

    cenarios = [
        {"capital": 10, "risco": 0.02, "entrada": 1.00, "stop": 0.97,
         "label": "Spot $10, 2% risco, stop 3%"},
        {"capital": 10, "risco": 0.02, "entrada": 2.00, "stop": 1.90,
         "label": "Futuro $10, 2% risco, stop 5% (5x lev)"},
        {"capital": 500, "risco": 0.02, "entrada": 5000, "stop": 4900,
         "label": "B3 R$500, 2% risco, stop 2%"},
    ]

    for c in cenarios:
        print(f"\n  --- {c['label']} ---")
        result = calcular_tamanho_posicao(
            c["capital"], c["risco"], c["entrada"], c["stop"]
        )
        if result:
            print(f"  Tamanho posicao:  ${result['tamanho_usd']}")
            print(f"  Valor em risco:   ${result['valor_risco']}")
            print(f"  Stop distancia:   {result['stop_distancia_pct']}%")
            print(f"  Peso carteira:    {result['peso_carteira']}%")
            print(f"  Risco restante:   {result['risco_restante_pct']}%")

    print()


def relatorio_kelly():
    """Demonstra Kelly Criterion."""
    print("\n" + "=" * 60)
    print("  KELLY CRITERION")
    print("=" * 60)

    cenarios = [
        {"wr": 0.40, "avg_win": 0.06, "avg_loss": 0.03,
         "label": "Spot historico (40% WR, ganho 2x perda)"},
        {"wr": 0.50, "avg_win": 0.04, "avg_loss": 0.02,
         "label": "Futuro ideal (50% WR, ganho 2x perda)"},
        {"wr": 0.30, "avg_win": 0.08, "avg_loss": 0.03,
         "label": "Trend following (30% WR, ganho alto)"},
    ]

    for c in cenarios:
        k = kelly_criterion(c["wr"], c["avg_win"], c["avg_loss"])
        print(f"\n  --- {c['label']} ---")
        print(f"  Win Rate:    {c['wr']*100:.0f}%")
        print(f"  Odds:        {k['odds']}")
        print(f"  Kelly %:     {k['kelly_pct']}%")
        print(f"  1/4 Kelly:   {k['kelly_frac']}% (recomendado)")
        print(f"  Classificacao: {k['fracao']}")

    print()


def relatorio_backtest(par=None, saldo=500, candles=6000):
    """Roda backtest completo e compara com buy-and-hold."""
    print("\n" + "=" * 60)
    print("  BACKTEST + COMPARACAO vs BUY-AND-HOLD")
    print("=" * 60)

    pares = [par] if par else PARES

    for p in pares:
        print(f"\n  Rodando backtest para {p}...")
        try:
            trades = backtest(p, saldo, "5m", candles,
                            STOP_PCT, ROI_TABELA, USAR_FILTRO)

            if trades:
                imprimir_analise_completa(trades, p, saldo)
                imprimir_comparacao_bh(trades, p, "5m", candles, saldo)

                k = kelly_criterion(
                    len([t for t in trades if t["resultado"] == "ganho"]) / len(trades),
                    sum(t["lucro_reais"] for t in trades if t["resultado"] == "ganho") /
                        len([t for t in trades if t["resultado"] == "ganho"]),
                    sum(t["lucro_reais"] for t in trades if t["resultado"] == "perda") /
                        len([t for t in trades if t["resultado"] == "perda"]),
                )
                print(f"\n  Kelly para este par:")
                print(f"    Kelly %:     {k['kelly_pct']}%")
                print(f"    1/4 Kelly:   {k['kelly_frac']}%")
                print(f"    Classificacao: {k['fracao']}")
            else:
                print(f"  {p}: Nenhum trade gerado")

        except Exception as e:
            print(f"  Erro no backtest de {p}: {e}")

        import time
        time.sleep(0.5)


def relatorio_todos(saldo=500, candles=6000):
    """Backtest de todos os pares combinados."""
    print("\n" + "=" * 60)
    print("  BACKTEST - TODOS OS PARES COMBINADOS")
    print("=" * 60)

    todos = backtest_todos(saldo, "5m", candles)
    if todos:
        from spot.strategy import imprimir, imprimir_resumo
        imprimir(todos, "Todos os Pares", saldo)
        imprimir_resumo(todos, saldo)
    else:
        print("  Nenhum trade gerado em nenhum par")


def avaliar_exemplo():
    """Demonstra avaliacao de trade."""
    print("\n" + "=" * 60)
    print("  AVALIACAO DE TRADE")
    print("=" * 60)

    trade = avaliar_trade(
        preco=1.567,
        stop=1.51999,
        alvo=1.61401,
        capital=10,
        risco_pct=0.02,
        alavancagem=1,
    )

    if trade.get("valido"):
        print(f"  R:R:          {trade['rr']}")
        print(f"  RR aceitavel: {'SIM' if trade['rr_aceitavel'] else 'NAO'} (min 2.0)")
        print(f"  Tamanho:      ${trade['tamanho']['tamanho_usd']}")
        print(f"  Risco:        ${trade['risco_valor']}")
        print(f"  Recompensa:   ${trade['recompensa_valor']}")
        print(f"  Risco pesado: {'SIM' if trade['risco_pesado'] else 'NAO'}")
    else:
        print(f"  Trade invalido: {trade.get('motivo')}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Analise de Trading")
    parser.add_argument("--par", default=None, help="Par especifico (ex: ATOMUSDT)")
    parser.add_argument("--saldo", type=float, default=500, help="Capital inicial")
    parser.add_argument("--candles", type=int, default=6000, help="Numero de candles")
    parser.add_argument("--risk", action="store_true", help="Mostrar risk management")
    parser.add_argument("--kelly", action="store_true", help="Mostrar Kelly Criterion")
    parser.add_argument("--backtest", action="store_true", help="Rodar backtest")
    parser.add_argument("--all", action="store_true", help="Tudo")
    args = parser.parse_args()

    print("\n  ========================================")
    print("  RELATORIO DE ANALISE - TRADING BOTS")
    print("  ========================================")
    print(f"  Data: {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Capital: R${args.saldo:.2f}")
    print(f"  Candles: {args.candles}")

    if args.all or args.risk:
        relatorio_risk_management()
        relatorio_kelly()
        avaliar_exemplo()

    if args.all or args.backtest:
        if args.par:
            relatorio_backtest(args.par, args.saldo, args.candles)
        else:
            relatorio_backtest(saldo=args.saldo, candles=args.candles)
            relatorio_todos(args.saldo, args.candles)

    if not any([args.risk, args.kelly, args.backtest, args.all]):
        print("\n  Use --risk, --kelly, --backtest ou --all")
        print("  Exemplos:")
        print("    python analise.py --all")
        print("    python analise.py --backtest --par ATOMUSDT")
        print("    python analise.py --risk")
        print("    python analise.py --kelly")


if __name__ == "__main__":
    main()
