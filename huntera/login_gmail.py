"""Login unico no Gmail com o navegador do bot.
Abre a janela visivel, vai ao Gmail, voce loga (digita email/senha na janela),
e quando terminar (a pagina do Gmail carregar), salva a sessao completa
(inclui cookies do Google) pra ficar sempre conectado nas proximas execucoes.

Uso:  python login_gmail.py
"""
import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("login_gmail")

from engine_huntera import HunteraBot

bot = HunteraBot()
try:
    # Abre o navegador do bot (janela visivel) e vai pro Gmail
    if not bot.iniciar(visivel=True):
        print("Falha ao abrir o navegador do bot.")
        sys.exit(1)

    # Vai pro Gmail
    print("Abrindo Gmail na janela do bot...")
    try:
        bot.page.goto("https://accounts.google.com", wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print("Aviso navegacao: %s" % e)
    time.sleep(4)

    print("=" * 60)
    print("Faça login no SEU Gmail na janela que abriu (digite email e senha).")
    print("Quando terminar de logar e a pagina mostrar sua conta, pressione ENTER aqui.")
    print("=" * 60)
    input("Pressione ENTER apos terminar o login no Gmail...")

    # Mantem a janela aberta um instante e salva a sessao completa
    time.sleep(2)
    bot._save_browser_session()
    print("Sessao salva! Cookies do Google guardados pra ficar sempre conectado.")

    # Voltamos pro jogo pra nao quebrar o farm
    try:
        bot.page.goto("https://huntera.com.br/game", wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print("Aviso: %s" % e)
    time.sleep(2)
    bot._save_browser_session()
    print("Pronto! O email ficara sempre conectado no navegador do bot.")
except Exception as e:
    import traceback; traceback.print_exc()
finally:
    bot.fechar()
