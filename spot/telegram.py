import requests
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BOT_DIR, "spot", "telegram_config.txt")


def carregar_config():
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")

    if token and chat_id:
        return token, chat_id

    if not os.path.exists(CONFIG_FILE):
        return None, None
    with open(CONFIG_FILE, "r") as f:
        linhas = f.read().strip().split("\n")
    for linha in linhas:
        if linha.startswith("TOKEN="):
            token = linha.split("=", 1)[1].strip()
        elif linha.startswith("CHAT_ID="):
            chat_id = linha.split("=", 1)[1].strip()
    return token, chat_id


def salvar_config(token, chat_id):
    with open(CONFIG_FILE, "w") as f:
        f.write("TOKEN={}\n".format(token))
        f.write("CHAT_ID={}\n".format(chat_id))


def enviar_mensagem(texto):
    token, chat_id = carregar_config()
    if not token or not chat_id:
        return False, "Telegram nao configurado"

    url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    payload = {
        "chat_id": chat_id,
        "text": texto,
    }

    try:
        resposta = requests.post(url, json=payload, timeout=10)
        if resposta.status_code == 200:
            return True, "OK"
        else:
            return False, "Erro {}".format(resposta.status_code)
    except Exception as e:
        return False, str(e)


def formatar_sinal(sinal):
    if sinal["sinal"] == "COMPRA":
        tag = "COMPRA"
    else:
        tag = "VENDA"

    preco = float(sinal["preco"])
    rsi = float(sinal["rsi"])
    stop = float(sinal["stop"])
    alvo = float(sinal["alvo"])

    texto = (
        "* {} {}*\n"
        "\n"
        "Preco: ${:.6f}\n"
        "RSI: {:.1f}\n"
        "Tendencia: {}\n"
        "\n"
        "ENTRADA: ${:.6f}\n"
        "STOP LOSS: ${:.6f}\n"
        "TAKE PROFIT: ${:.6f}\n"
        "\n"
        "Motivo: {}\n"
        "\n"
        "Gerencie seu risco!"
    ).format(
        tag, sinal["par"],
        preco,
        rsi,
        sinal["tendencia"],
        preco,
        stop,
        alvo,
        sinal["motivo"],
    )
    return texto


def testar_conexao():
    token, chat_id = carregar_config()
    if not token or not chat_id:
        return False, "Configure o Telegram primeiro"

    ok, msg = enviar_mensagem("[BOT] Bot Spot conectado! Sinais de trading serao enviados aqui.")
    if ok:
        return True, "Mensagem enviada com sucesso!"
    else:
        return False, "Erro: {}".format(msg)
