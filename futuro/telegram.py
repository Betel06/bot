import requests
import os

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carregar_config():
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
    chat_ids = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")
    if chat_ids:
        chat_ids = [c.strip() for c in str(chat_ids).replace(";", ",").split(",") if c.strip()]
    else:
        chat_ids = []
    return token, chat_ids


def enviar_mensagem(texto, chat_id=None):
    token, chats = carregar_config()
    if not token or not chats:
        return False, "Telegram nao configurado"

    alvos = [str(chat_id)] if chat_id else chats

    url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    ok = False
    ultimo_erro = None
    for cid in alvos:
        payload = {"chat_id": cid, "text": texto}
        try:
            resposta = requests.post(url, json=payload, timeout=10)
            if resposta.status_code == 200:
                ok = True
            else:
                ultimo_erro = "Erro {} em {}".format(resposta.status_code, cid)
        except Exception as e:
            ultimo_erro = str(e)
    return (ok, "OK") if ok else (False, ultimo_erro or "erro")


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
        "⚡ Alavancagem: 5x | Gerencie o risco!"
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
    alav = res.get("alavancagem")
    if alav:
        texto += "\n⚡ Alavancagem: {}x aplicada".format(alav)
    return texto
