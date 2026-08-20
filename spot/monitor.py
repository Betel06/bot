import sys
import time
import os
from datetime import datetime

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from spot.config import PARES, INTERVALO_MONITOR, STOP_PCT
from spot.strategy import analisar
from spot.telegram import carregar_config, enviar_mensagem, formatar_sinal
from core.dados import buscar_historico
from core.indicadores import calcular_rsi


def checar_sinais():
    sinais = []
    for par in PARES:
        try:
            r = analisar(par)
            if r and r["sinal"]:
                sinais.append(r)
        except Exception as e:
            print("  [ERRO] {}: {}".format(par, e))
        time.sleep(0.3)
    return sinais


def checar_posicoes(posicoes_abertas):
    resultado = []
    for pos in list(posicoes_abertas):
        try:
            df = buscar_historico(pos["par"], "5m", 10)
            if df is None or len(df) == 0:
                continue

            preco_atual = float(df["close"].iloc[-1])
            preco_alta = float(df["high"].iloc[-1])
            preco_baixa = float(df["low"].iloc[-1])

            if pos["direcao"] == "COMPRA":
                if preco_baixa <= pos["stop"]:
                    lucro = (pos["stop"] - pos["entrada"]) / pos["entrada"]
                    resultado.append({**pos, "tipo": "STOP LOSS", "preco_saida": pos["stop"],
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro * pos["valor_pos"]})
                    posicoes_abertas.remove(pos)
                elif preco_alta >= pos["alvo"]:
                    lucro = (pos["alvo"] - pos["entrada"]) / pos["entrada"]
                    resultado.append({**pos, "tipo": "TAKE PROFIT", "preco_saida": pos["alvo"],
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro * pos["valor_pos"]})
                    posicoes_abertas.remove(pos)
            else:
                if preco_alta >= pos["stop"]:
                    lucro = (pos["entrada"] - pos["stop"]) / pos["entrada"]
                    resultado.append({**pos, "tipo": "STOP LOSS", "preco_saida": pos["stop"],
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro * pos["valor_pos"]})
                    posicoes_abertas.remove(pos)
                elif preco_baixa <= pos["alvo"]:
                    lucro = (pos["entrada"] - pos["alvo"]) / pos["entrada"]
                    resultado.append({**pos, "tipo": "TAKE PROFIT", "preco_saida": pos["alvo"],
                                     "lucro_pct": lucro * 100, "lucro_usd": lucro * pos["valor_pos"]})
                    posicoes_abertas.remove(pos)

            pos["preco_atual"] = preco_atual
        except Exception:
            pass

    return resultado


def formatar_resultado(res):
    if res["tipo"] == "TAKE PROFIT":
        tag = "WIN"
    else:
        tag = "LOSS"

    texto = (
        "* {} {} {}*\n"
        "\n"
        "Par: {}\n"
        "Direcao: {}\n"
        "Entrada: ${:.6f}\n"
        "Saida: ${:.6f}\n"
        "\n"
        "Resultado: {} ({:+.2f}%)\n"
        "Lucro/Perda: ${:+.2f}\n"
    ).format(
        tag, res["tipo"], res["par"],
        res["par"],
        res["direcao"],
        res["entrada"],
        res["preco_saida"],
        res["tipo"],
        res["lucro_pct"],
        res["lucro_usd"],
    )
    return texto


def formatar_resumo(wins, losses, total_lucro):
    if total_lucro >= 0:
        status = "POSITIVO"
    else:
        status = "NEGATIVO"

    texto = (
        "* RESUMO DIARIO*\n"
        "\n"
        "Wins: {}\n"
        "Losses: {}\n"
        "Total: {}\n"
        "\n"
        "Resultado: ${:+.2f} {}\n"
    ).format(
        wins,
        losses,
        wins + losses,
        total_lucro,
        status,
    )
    return texto


def monitorar():
    token, chat_id = carregar_config()
    telegram_ok = token is not None and chat_id is not None

    print("=" * 60)
    print("  MONITOR SPOT — SINAIS + RESULTADOS")
    print("  Pares: {}".format(", ".join(PARES)))
    print("  Intervalo: {} min".format(INTERVALO_MONITOR // 60))
    if telegram_ok:
        print("  Telegram: CONECTADO")
    else:
        print("  Telegram: DESCONECTADO")
    print("=" * 60)
    print("\n  Iniciando monitor...")
    print("  Ctrl+C para parar\n")

    historico = []
    posicoes_abertas = []
    wins = 0
    losses = 0
    total_lucro = 0.0
    inicio = datetime.now()
    rodada = 0

    while True:
        rodada += 1
        agora = datetime.now()
        print("\n  [Rodada {} | {}]".format(rodada, agora.strftime('%H:%M:%S')))

        resultados = checar_posicoes(posicoes_abertas)
        for res in resultados:
            tag = "WIN" if res["tipo"] == "TAKE PROFIT" else "LOSS"
            print("\n  [{}] {} {} | ${:+.2f} ({:+.2f}%)".format(
                tag, res["tipo"], res["par"], res["lucro_usd"], res["lucro_pct"]))

            if telegram_ok:
                msg = formatar_resultado(res)
                ok, erro = enviar_mensagem(msg)
                if ok:
                    print("  [TELEGRAM] Resultado enviado!")
                else:
                    print("  [TELEGRAM] Erro: {}".format(erro))

            if res["tipo"] == "TAKE PROFIT":
                wins += 1
            else:
                losses += 1
            total_lucro += res["lucro_usd"]

        if posicoes_abertas:
            print("\n  Posicoes abertas:")
            for pos in posicoes_abertas:
                lucro_atual = (pos["preco_atual"] - pos["entrada"]) / pos["entrada"] * 100
                print("    {} | {} | ${:.6f} | Atual: ${:.6f} ({:+.2f}%)".format(
                    pos["par"], pos["direcao"], pos["entrada"], pos["preco_atual"], lucro_atual))

        print("\n  Score: {}W / {}L | Total: ${:+.2f}".format(wins, losses, total_lucro))

        sinais = checar_sinais()

        if sinais:
            for s in sinais:
                ja_notificado = any(
                    h["par"] == s["par"] and h["sinal"] == s["sinal"]
                    for h in historico[-50:]
                )

                if not ja_notificado:
                    print("\n  [SINAL] {} {}".format(s["sinal"], s["par"]))
                    print("    Preco: ${:.6f} | Stop: ${:.6f} | Alvo: ${:.6f}".format(
                        s["preco"], s["stop"], s["alvo"]))

                    posicoes_abertas.append({
                        "par": s["par"],
                        "direcao": s["sinal"],
                        "entrada": s["preco"],
                        "stop": s["stop"],
                        "alvo": s["alvo"],
                        "valor_pos": 10.0,
                        "data": agora.strftime("%d/%m %H:%M"),
                        "preco_atual": s["preco"],
                    })

                    if telegram_ok:
                        msg = formatar_sinal(s)
                        ok, erro = enviar_mensagem(msg)
                        if ok:
                            print("  [TELEGRAM] Sinal enviado!")
                        else:
                            print("  [TELEGRAM] Erro: {}".format(erro))

                    historico.append({
                        "par": s["par"],
                        "sinal": s["sinal"],
                        "preco": s["preco"],
                        "rsi": s["rsi"],
                        "data": agora.strftime("%d/%m %H:%M"),
                    })
        else:
            print("  Nenhum sinal novo.")

        tempo_decorrido = (datetime.now() - inicio).total_seconds() / 60
        print("\n  Rodando ha {:.0f} min | {} sinais | {} posicoes abertas".format(
            tempo_decorrido, len(historico), len(posicoes_abertas)))
        print("  Proxima checagem em {} min...".format(INTERVALO_MONITOR // 60))
        print("  Ctrl+C para parar")

        try:
            time.sleep(INTERVALO_MONITOR)
        except KeyboardInterrupt:
            print("\n\n  Monitor parado.")
            print("\n  RESUMO FINAL:")
            print("  Wins: {}".format(wins))
            print("  Losses: {}".format(losses))
            print("  Total: ${:+.2f}".format(total_lucro))

            if telegram_ok and (wins + losses) > 0:
                msg = formatar_resumo(wins, losses, total_lucro)
                enviar_mensagem(msg)

            if historico:
                print("\n  Historico de sinais:")
                for h in historico[-10:]:
                    print("    {} | {} | {} | RSI:{:.1f}".format(
                        h["data"], h["sinal"], h["par"], h["rsi"]))
            break


if __name__ == "__main__":
    monitorar()
