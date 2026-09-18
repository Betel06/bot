"""Huntera Bot - Runner persistente com auto-restart e Telegram."""
import os
import sys
import json
import time
import logging
import threading
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine_huntera import HunteraBot
from huntera_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_NOTIF_INTERVALO

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_huntera.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("huntera_runner")

STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json")
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


def send_telegram(msg):
    """Envia mensagem pro Telegram."""
    try:
        url = "https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                      timeout=10)
    except Exception as e:
        logger.debug("Telegram erro: %s", e)


def save_status(estado):
    """Salva status em JSON."""
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def format_status(estado):
    """Formata status pro Telegram."""
    hp_pct = int(estado["hp"] * 100 / estado["hp_max"]) if estado["hp_max"] else 0
    mp_pct = int(estado["mp"] * 100 / estado["mp_max"]) if estado["mp_max"] else 0
    return (
        "<b>Huntera Bot</b>\n"
        "LV: <b>{level}</b>\n"
        "HP: {hp}/{hp_max} ({hp_pct}%)\n"
        "MP: {mp}/{mp_max} ({mp_pct}%)\n"
        "CAP: {cap:.0f} oz\n"
        "Caçada: {cacada}\n"
        "Dispatches: {dispatches}\n"
        "Poções: {pocoes}\n"
        "Ciclos: {ciclos}\n"
        "Ultimo: {update}"
    ).format(
        level=estado["level"],
        hp=estado["hp"], hp_max=estado["hp_max"], hp_pct=hp_pct,
        mp=estado["mp"], mp_max=estado["mp_max"], mp_pct=mp_pct,
        cap=estado["capacity_oz"],
        cacada=estado.get("caçada_atual", "?"),
        dispatches=estado["dispatches_feitos"],
        pocoes=estado["pocoes_usadas"],
        ciclos=estado["total_rodadas"],
        update=estado.get("ultimo_update", "?")
    )


def main():
    logger.info("=" * 50)
    logger.info("HUNTERA BOT - Iniciando runner persistente")
    logger.info("=" * 50)

    send_telegram("🤖 <b>Huntera Bot iniciado!</b> Rodando em background...")

    ultimo_telegram = time.time()
    consecutive_errors = 0
    MAX_ERRORS = 5

    while True:
        bot = None
        try:
            bot = HunteraBot()
            if not bot.iniciar():
                logger.error("Falha ao iniciar bot!")
                time.sleep(30)
                continue

            consecutive_errors = 0
            logger.info("Bot rodando! Ciclos infinitos...")

            ciclo = 0
            while bot.running:
                estado = bot.rodar_ciclo()
                ciclo += 1
                save_status(estado)

                # Log a cada 10 ciclos
                if ciclo % 10 == 0:
                    hp_pct = int(estado["hp"] * 100 / estado["hp_max"]) if estado["hp_max"] else 0
                    mp_pct = int(estado["mp"] * 100 / estado["mp_max"]) if estado["mp_max"] else 0
                    logger.info(
                        "[Ciclo %d] LV=%d HP=%d%% MP=%d%% CAP=%.0f dispatch=%d",
                        ciclo, estado["level"], hp_pct, mp_pct,
                        estado["capacity_oz"], estado["dispatches_feitos"]
                    )

                # Telegram a cada 30 min
                agora = time.time()
                if agora - ultimo_telegram >= TELEGRAM_NOTIF_INTERVALO:
                    msg = format_status(estado)
                    send_telegram(msg)
                    ultimo_telegram = agora
                    logger.info("Telegram enviado!")

                time.sleep(8)

        except KeyboardInterrupt:
            logger.info("Interrompido pelo usuario")
            if bot:
                bot.fechar()
            send_telegram("🛑 <b>Huntera Bot parado!</b> (usuario)")
            return

        except Exception as e:
            consecutive_errors += 1
            logger.error("Erro no runner (tentativa %d/%d): %s",
                         consecutive_errors, MAX_ERRORS, e)

            if consecutive_errors >= MAX_ERRORS:
                send_telegram("⚠️ <b>Huntera Bot com erros!</b> %d erros consecutivos: %s" % (consecutive_errors, str(e)[:100]))
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
