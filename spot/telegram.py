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
            data = resposta.json()
            return True, data.get("result", {}).get("message_id")
        else:
            return False, "Erro {}".format(resposta.status_code)
    except Exception as e:
        return False, str(e)


def editar_mensagem(message_id, texto):
    token, chat_id = carregar_config()
    if not token or not chat_id:
        return False, "Telegram nao configurado"

    url = "https://api.telegram.org/bot{}/editMessageText".format(token)
    payload = {"chat_id": chat_id, "message_id": message_id, "text": texto}

    try:
        resposta = requests.post(url, json=payload, timeout=10)
        if resposta.status_code == 200:
            return True, "OK"
        return False, "Erro {}".format(resposta.status_code)
    except Exception as e:
        return False, str(e)


def fixar_mensagem(message_id):
    token, chat_id = carregar_config()
    if not token or not chat_id:
        return False, "Telegram nao configurado"

    url = "https://api.telegram.org/bot{}/pinChatMessage".format(token)
    payload = {"chat_id": chat_id, "message_id": message_id}

    try:
        resposta = requests.post(url, json=payload, timeout=10)
        if resposta.status_code == 200:
            return True, "OK"
        return False, "Erro {}".format(resposta.status_code)
    except Exception as e:
        return False, str(e)


def formatar_sinal(sinal):
    if sinal["sinal"] == "COMPRA":
        tag = "COMPRA 🔼"
        emoji = "🟩"
    else:
        tag = "VENDA 🔽"
        emoji = "🟥"

    preco = float(sinal["preco"])
    rsi = float(sinal["rsi"])
    stop = float(sinal["stop"])
    alvo = float(sinal["alvo"])

    texto = (
        "{0}{0}{0} TRADER SPOT {0}{0}{0}\n"
        "🟢📈 COMPRA E VENDA - SPOT 📈🟢\n"
        "----------------------------\n"
        "\n"
        "{1} {2} {3}\n"
        "\n"
        "Preco: ${4:.6f}\n"
        "Forca do sinal: {5:.1f}\n"
        "Tendencia: {6}\n"
        "\n"
        "🎯 ALVO: ${7:.6f}\n"
        "🛑 STOP: ${8:.6f}\n"
        "\n"
        "📖 Leitura: {9}\n"
        "\n"
        "Gerencie seu risco!"
    ).format(
        "🟢", emoji, tag, sinal["par"],
        preco,
        rsi,
        sinal["tendencia"],
        alvo,
        stop,
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
