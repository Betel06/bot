"""Runner VISIVEL - abre o jogo numa janela pra acompanhar + farm automatico."""
import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine_huntera import HunteraBot
from huntera_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_NOTIF_INTERVALO
import requests, json

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_huntera_visivel.log")
STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("huntera_visivel")


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post("https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN,
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.debug("Telegram erro: %s", e)


def save_status(estado):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def format_status(estado):
    hp_pct = int(estado["hp"] * 100 / estado["hp_max"]) if estado["hp_max"] else 0
    mp_pct = int(estado["mp"] * 100 / estado["mp_max"]) if estado["mp_max"] else 0
    return (
        "<b>Huntera Bot (visivel)</b>\n"
        "LV: <b>{level}</b>\n"
        "HP: {hp}/{hp_max} ({hp_pct}%)\n"
        "MP: {mp}/{mp_max} ({mp_pct}%)\n"
        "CAP: {cap:.0f} oz\n"
        "Dispatches: {dispatches} | Pocoes: {pocoes}\n"
        "Ciclos: {ciclos}"
    ).format(
        level=estado["level"], hp=estado["hp"], hp_max=estado["hp_max"], hp_pct=hp_pct,
        mp=estado["mp"], mp_max=estado["mp_max"], mp_pct=mp_pct,
        cap=estado["capacity_oz"], dispatches=estado["dispatches_feitos"],
        pocoes=estado["pocoes_usadas"], ciclos=estado["total_rodadas"],
    )


def main():
    logger.info("=" * 50)
    logger.info("HUNTERA BOT (VISIVEL) - janela aberta pra acompanhar")
    logger.info("=" * 50)
    send_telegram("🤖 <b>Huntera Bot visivel iniciado!</b> Janela aberta pra acompanhar.")

    ultimo_telegram = time.time()
    consecutive_errors = 0
    MAX_ERRORS = 5

    while True:
        bot = None
        try:
            bot = HunteraBot()
            if not bot.iniciar(visivel=True):
                logger.error("Falha ao iniciar bot!")
                time.sleep(30)
                continue

            consecutive_errors = 0
            logger.info("Bot rodando! Janela visivel. (feche este console p/ parar: use Ctrl+C)")
            ciclo = 0
            while bot.running:
                estado = bot.rodar_ciclo()
                ciclo += 1
                save_status(estado)
                if ciclo % 10 == 0:
                    hp_pct = int(estado["hp"] * 100 / estado["hp_max"]) if estado["hp_max"] else 0
                    mp_pct = int(estado["mp"] * 100 / estado["mp_max"]) if estado["mp_max"] else 0
                    logger.info("[Ciclo %d] LV=%d HP=%d%% MP=%d%% CAP=%.0f dispatch=%d",
                                ciclo, estado["level"], hp_pct, mp_pct,
                                estado["capacity_oz"], estado["dispatches_feitos"])
                agora = time.time()
                if agora - ultimo_telegram >= TELEGRAM_NOTIF_INTERVALO:
                    send_telegram(format_status(estado))
                    ultimo_telegram = agora
                time.sleep(8)

        except KeyboardInterrupt:
            logger.info("Interrompido pelo usuario (Ctrl+C)")
            if bot:
                bot.fechar()
            send_telegram("🛑 <b>Huntera Bot visivel parado!</b> (usuario)")
            return
        except Exception as e:
            consecutive_errors += 1
            logger.error("Erro (tentativa %d/%d): %s", consecutive_errors, MAX_ERRORS, e)
            if consecutive_errors >= MAX_ERRORS:
                send_telegram("⚠️ Huntera visivel com erros: %s" % str(e)[:100])
                consecutive_errors = 0
            if bot:
                try:
                    bot.fechar()
                except Exception:
                    pass
            time.sleep(15)
            logger.info("Reiniciando...")


if __name__ == "__main__":
    main()
