import requests
import os

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carregar_config():
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")
    return token, chat_id


def enviar_mensagem(texto):
    token, chat_id = carregar_config()
    if not token or not chat_id:
        return False, "Telegram nao configurado"

    url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    payload = {"chat_id": chat_id, "text": texto}

    try:
        resposta = requests.post(url, json=payload, timeout=10)
        if resposta.status_code == 200:
            return True, "OK"
        return False, "Erro {}".format(resposta.status_code)
    except Exception as e:
        return False, str(e)


def formatar_sinal(sinal):
    if sinal["sinal"] == "COMPRA":
        tag = "LONG 🔼"
        emoji = "🟩"
    else:
        tag = "SHORT 🔽"
        emoji = "🟥"

    preco = float(sinal["preco"])
    conf = float(sinal["rsi"])
    stop = float(sinal["stop"])
    alvo = float(sinal["alvo"])

    texto = (
        "{0}{0}{0} TRADER FUTURO {0}{0}{0}\n"
        "🔵⚡ DAY TRADE - FUTUROS ⚡🔵\n"
        "============================\n"
        "\n"
        "{1} {2} {3}\n"
        "\n"
        "Par: {4}\n"
        "Entrada: ${5:.6f}\n"
        "Confianca IA: {6:.0f}%\n"
        "\n"
        "🎯 ALVO: ${7:.6f}\n"
        "🛑 STOP: ${8:.6f}\n"
        "\n"
        "📖 Leitura: {9}\n"
        "\n"
        "⚡ Alavancagem com moderacao. Gerencie o risco!"
    ).format(
        "🔵", emoji, tag, sinal["par"],
        sinal["par"],
        preco,
        conf,
        alvo,
        stop,
        sinal["motivo"],
    )
    return texto


def formatar_resultado(res):
    if res["tipo"] == "TAKE PROFIT":
        tag = "WIN ✅"
        emoji = "🔵🟢"
    else:
        tag = "LOSS ❌"
        emoji = "🔵🔴"

    texto = (
        "{0} TRADER FUTURO | {1}\n"
        "============================\n"
        "\n"
        "Par: {2} ({3})\n"
        "Entrada: ${4:.6f}\n"
        "Saida: ${5:.6f}\n"
        "\n"
        "Resultado: {6} ({7:+.2f}%)\n"
        "P/L: ${8:+.2f}\n"
    ).format(
        emoji, tag,
        res["par"], res["direcao"],
        float(res["entrada"]),
        float(res["preco_saida"]),
        res["tipo"],
        float(res["lucro_pct"]),
        float(res["lucro_usd"]),
    )
    return texto
