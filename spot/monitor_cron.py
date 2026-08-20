import sys
import os
import json
from datetime import datetime

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from spot.config import PARES
from spot.strategy import analisar
from spot.telegram import carregar_config, enviar_mensagem, formatar_sinal


def checar_sinais():
    sinais = []
    for par in PARES:
        try:
            r = analisar(par)
            if r and r["sinal"]:
                sinais.append(r)
        except Exception as e:
            print("Erro {}: {}".format(par, e))
    return sinais


def carregar_historico():
    caminho = os.path.join(BOT_DIR, "logs", "sinais_historico.json")
    if os.path.exists(caminho):
        with open(caminho, "r") as f:
            return json.load(f)
    return []


def salvar_historico(historico):
    caminho = os.path.join(BOT_DIR, "logs", "sinais_historico.json")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w") as f:
        json.dump(historico[-200:], f)


def rodar():
    token, chat_id = carregar_config()
    telegram_ok = token is not None and chat_id is not None

    historico = carregar_historico()
    sinais = checar_sinais()

    agora = datetime.now().strftime("%d/%m %H:%M")
    enviados = 0

    for s in sinais:
        ja_notificado = any(
            h["par"] == s["par"] and h["sinal"] == s["sinal"]
            for h in historico[-100:]
        )

        if not ja_notificado:
            print("SINAL: {} {} | RSI:{:.1f} | ${:.6f}".format(
                s["sinal"], s["par"], s["rsi"], s["preco"]))

            if telegram_ok:
                msg = formatar_sinal(s)
                ok, erro = enviar_mensagem(msg)
                if ok:
                    print("Telegram enviado!")
                    enviados += 1
                else:
                    print("Telegram erro: {}".format(erro))

            historico.append({
                "par": s["par"],
                "sinal": s["sinal"],
                "preco": s["preco"],
                "rsi": s["rsi"],
                "data": agora,
            })

    salvar_historico(historico)

    if enviados == 0:
        print("[{}] Nenhum sinal novo | {} sinais no historico".format(
            agora, len(historico)))
    else:
        print("[{}] {} sinais enviados | {} no historico".format(
            agora, enviados, len(historico)))


if __name__ == "__main__":
    rodar()
