import os
import sys
import time

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from spot.config import PARES, STOP_PCT, ROI_TABELA, INTERVALO, USAR_FILTRO, SALDO_INICIAL
from spot.strategy import analisar, backtest, backtest_todos, imprimir, imprimir_resumo


def banner():
    os.system("cls" if os.name == "nt" else "clear")
    filtro = "SIM" if USAR_FILTRO else "NAO"
    print("=" * 55)
    print("  SPOT TRADING BOT")
    print("  {} | Stop {}% | {}".format(INTERVALO, int(STOP_PCT*100), "com filtro" if USAR_FILTRO else "sem filtro"))
    print("  Pares: {}".format(", ".join(PARES)))
    print("=" * 55)


def opcao_analisar():
    par = input("\nPar (ou 'todos'): ").strip().upper()
    if par == "TODOS" or par == "":
        for p in PARES:
            r = analisar(p)
            if r:
                sinal = r["sinal"] or "---"
                print("  {} | RSI:{:5.1f} | {:6s} | {}".format(
                    p, r["rsi"], r["tendencia"], sinal))
            time.sleep(0.3)
    else:
        if not par:
            par = PARES[0]
        r = analisar(par)
        if r:
            print("\n  {} | ${:.4f} | RSI: {:.1f} | {}".format(
                r["par"], r["preco"], r["rsi"], r["tendencia"]))
            print("  Sinal: {}".format(r["sinal"] or "NEUTRO"))
            if r["sinal"]:
                print("  Motivo: {}".format(r["motivo"]))
                print("  Stop: ${:.4f} | Alvo: ${:.4f}".format(r["stop"], r["alvo"]))


def opcao_backtest():
    saldo = input_float("Capital (R$) [{}]: ".format(SALDO_INICIAL), SALDO_INICIAL)
    print("\nRodando backtest ({}, stop {}%, {}):".format(
        INTERVALO, int(STOP_PCT*100), "com filtro" if USAR_FILTRO else "sem filtro"))

    for par in PARES:
        trades = backtest(par, saldo=saldo)
        if trades:
            sf = trades[-1]["saldo"]
            total = len(trades)
            ganhos = sum(1 for t in trades if t["resultado"] == "ganho")
            lucro = sf - saldo
            wr = ganhos / total * 100
            print("  {:14s} | {:3d} trades | {:5.1f}% | R${:+7.2f}".format(
                par, total, wr, lucro))
        else:
            print("  {:14s} | 0 trades".format(par))
        time.sleep(0.1)

    print("\n  Todos juntos:")
    trades = backtest_todos(saldo=saldo)
    imprimir(trades, "BACKTEST {}".format(INTERVALO), saldo)
    imprimir_resumo(trades, saldo)


def opcao_testar():
    print("\n  TESTE RAPIDO — R$500 — 20 dias")
    print("  " + "-" * 40)
    saldo = 500
    trades = backtest_todos(saldo=saldo)
    imprimir(trades, "TESTE RAPIDO", saldo)
    imprimir_resumo(trades, saldo)


def opcao_monitorar():
    from spot.monitor import monitorar
    monitorar()


def opcao_telegram():
    from spot.telegram import carregar_config, salvar_config, testar_conexao

    token, chat_id = carregar_config()

    print("\n  CONFIGURAR TELEGRAM")
    print("  " + "-" * 40)

    if token and chat_id:
        print("  Status: CONECTADO")
        print("  Token: {}...{}".format(token[:10], token[-5:]))
        print("  Chat ID: {}".format(chat_id))
        print("\n  1 - Testar conexao")
        print("  2 - Reconfigurar")
        print("  3 - Voltar")

        op = input("\n  Escolha: ").strip()
        if op == "1":
            ok, msg = testar_conexao()
            if ok:
                print("\n  [OK] {}".format(msg))
            else:
                print("\n  [ERRO] {}".format(msg))
        elif op == "2":
            token = input("\n  Novo Token: ").strip()
            chat_id = input("  Novo Chat ID: ").strip()
            if token and chat_id:
                salvar_config(token, chat_id)
                print("  Configurado!")
                ok, msg = testar_conexao()
                print("  [{}] {}".format("OK" if ok else "ERRO", msg))
    else:
        print("  Status: DESCONECTADO")
        print()
        print("  Para configurar:")
        print("  1. Abra o Telegram e busque @BotFather")
        print("  2. Envie /newbot e siga as instrucoes")
        print("  3. Copie o TOKEN que o BotFather enviar")
        print("  4. Abra @userinfobot e copie seu CHAT_ID")
        print()
        token = input("  Token do Bot: ").strip()
        chat_id = input("  Seu Chat ID: ").strip()

        if token and chat_id:
            salvar_config(token, chat_id)
            print("\n  Configurado!")
            ok, msg = testar_conexao()
            print("  [{}] {}".format("OK" if ok else "ERRO", msg))
        else:
            print("\n  Configuracao cancelada.")


def input_float(mensagem, padrao):
    texto = input(mensagem).strip()
    if not texto:
        return padrao
    try:
        return float(texto)
    except ValueError:
        return padrao


def main():
    while True:
        banner()
        print("\n1 - Analisar pares")
        print("2 - Backtest (todos os pares)")
        print("3 - Teste rapido")
        print("4 - Monitor automatico")
        print("5 - Configurar Telegram")
        print("6 - Sair")

        opcao = input("\nEscolha: ").strip()

        if opcao == "1":
            opcao_analisar()
        elif opcao == "2":
            opcao_backtest()
        elif opcao == "3":
            opcao_testar()
        elif opcao == "4":
            opcao_monitorar()
        elif opcao == "5":
            opcao_telegram()
        elif opcao == "6":
            print("Saindo...")
            break

        input("\nEnter pra continuar...")


if __name__ == "__main__":
    main()
