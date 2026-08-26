"""
HUNTERA BOT ENGINE - Playwright headless com sessão salva.
Abre o jogo, monstra caça, monitora status, vai à cidade quando bolsa cheia.
"""
import os
import sys
import json
import time
import logging
import threading
from datetime import datetime

logger = logging.getLogger("huntera_engine")

SESSION_FILE = os.path.join(os.path.dirname(__file__), "huntera_session.json")
GAME_URL = "https://huntera.com.br/game"
LOCALSTORAGE_FILE = os.path.join(os.path.dirname(__file__), "huntera_localstorage.json")


class HunteraBot:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.running = False
        self.logado = False
        self.estado = {
            "level": 0,
            "hp": 0,
            "hp_max": 0,
            "mp": 0,
            "mp_max": 0,
            "xp": 0,
            "gold": 0,
            "lugar": "desconhecido",
            "caçando": False,
            "bolsa_cheia": False,
            "ultimo_update": None,
        }
        self._pw = None
        self._pw_instance = None

    def _start_pw(self):
        """Inicia Playwright de forma lazy."""
        if self._pw_instance is None:
            from playwright.sync_api import sync_playwright
            self._pw_instance = sync_playwright().start()
        return self._pw_instance

    def _load_session(self):
        """Carrega sessão salva."""
        if not os.path.exists(SESSION_FILE):
            logger.error("Sessão não encontrada! Execute login_huntera.py primeiro.")
            return False
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar sessão: {e}")
            return False

    def _save_session(self):
        """Salva sessão atual."""
        if self.context:
            try:
                storage = self.context.storage_state()
                with open(SESSION_FILE, "w", encoding="utf-8") as f:
                    json.dump(storage, f, indent=2, ensure_ascii=False)
                logger.info("Sessão salva com sucesso")
                return True
            except Exception as e:
                logger.error(f"Erro ao salvar sessão: {e}")
        return False

    def iniciar(self):
        """Inicia o bot com sessão salva."""
        storage = self._load_session()
        if not storage:
            return False

        pw = self._start_pw()

        logger.info("Iniciando navegador headless...")
        self.browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        # Cria contexto com sessão salva
        self.context = self.browser.new_context(
            storage_state=storage,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        # Injeta script anti-detection
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        self.page = self.context.new_page()
        self.running = True

        logger.info("Navegando para Huntera...")
        try:
            self.page.goto(GAME_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.warning(f"Aviso no carregamento: {e}")

        time.sleep(3)

        # Verifica se logou
        url_atual = self.page.url
        logger.info(f"URL atual: {url_atual}")

        # Salva screenshot para debug
        try:
            self.page.screenshot(path=os.path.join(os.path.dirname(__file__), "debug_estado.png"))
        except Exception:
            pass

        # Tenta detectar se está logado
        self.logado = self._verificar_login()
        if self.logado:
            logger.info("LOGIN OK! Bot logado no jogo.")
            self._extrair_estado()
        else:
            logger.warning("Login não detectado. Sessão pode ter expirado.")
            # Tenta extrair info de qualquer jeito
            self._extrair_estado()

        return self.logado

    def _verificar_login(self):
        """Verifica se o bot está logado no jogo."""
        try:
            # Procura por elementos que indicam jogo logado
            # (AJUSTAR conforme a interface real do Huntera)
            time.sleep(2)

            # Verifica se tem tela de login (significa DESLOGADO)
            login_buttons = self.page.query_selector_all('text="Logar com email"')
            if login_buttons:
                logger.warning("Tela de login detectada - DESLOGADO")
                return False

            # Verifica por elementos do jogo
            game_indicators = [
                'text="Hunt"',
                'text="Hunt Analyzer"',
                'text="Inventory"',
                'text="Backpack"',
                'text="Character"',
                'text="Map"',
            ]
            for indicator in game_indicators:
                try:
                    el = self.page.query_selector(indicator)
                    if el:
                        logger.info(f"Indicador de jogo encontrado: {indicator}")
                        return True
                except Exception:
                    pass

            # Se tem alguma barra de HP/MP, está logado
            hp_bar = self.page.query_selector('[class*="health"]') or \
                     self.page.query_selector('[class*="hp"]') or \
                     self.page.query_selector('[class*="life"]')
            if hp_bar:
                logger.info("Barra de HP detectada - logado")
                return True

            # Fallback: verifica URL
            if "/game" in self.page.url and "login" not in self.page.url.lower():
                logger.info("URL do jogo detectada, assumindo logado")
                return True

            return False
        except Exception as e:
            logger.error(f"Erro ao verificar login: {e}")
            return False

    def _extrair_estado(self):
        """Extrai dados do jogo da tela."""
        try:
            # Tenta extrair via JavaScript do localStorage/sessionStorage
            dados = self.page.evaluate("""() => {
                const result = {};
                try {
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        result['ls_' + key] = localStorage.getItem(key);
                    }
                } catch(e) {}
                try {
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const key = sessionStorage.key(i);
                        result['ss_' + key] = sessionStorage.getItem(key);
                    }
                } catch(e) {}
                return result;
            }""")

            if dados:
                logger.info(f"localStorage keys: {[k for k in dados.keys() if k.startswith('ls_')][:15]}")
                # Salva para debug
                debug_path = os.path.join(os.path.dirname(__file__), "debug_storage.json")
                with open(debug_path, "w", encoding="utf-8") as f:
                    json.dump(dados, f, indent=2, ensure_ascii=False)

            # Tenta extrair texto visível da página
            body_text = self.page.inner_text("body")
            if body_text:
                logger.info(f"Texto da página (primeiros 500 chars): {body_text[:500]}")

                # Salva para análise
                text_path = os.path.join(os.path.dirname(__file__), "debug_pagina.txt")
                with open(text_path, "w", encoding="utf-8") as f:
                    f.write(body_text)

            # Tenta extrair HTML relevante
            html = self.page.content()
            html_path = os.path.join(os.path.dirname(__file__), "debug_html.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"HTML salvo: {html_path} ({len(html)} bytes)")

            self.estado["ultimo_update"] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"Erro ao extrair estado: {e}")

    def capturar_pagina(self):
        """Captura screenshot e dados da página para análise."""
        if not self.page:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Screenshot
        try:
            path = os.path.join(os.path.dirname(__file__), f"capture_{timestamp}.png")
            self.page.screenshot(path=path)
            logger.info(f"Screenshot: {path}")
        except Exception as e:
            logger.error(f"Erro screenshot: {e}")

    def fechar(self):
        """Fecha o bot."""
        self.running = False
        self._save_session()
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self._pw_instance:
            try:
                self._pw_instance.stop()
            except Exception:
                pass
        logger.info("Bot fechado")


def main():
    """Modo standalone para teste."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    bot = HunteraBot()
    if bot.iniciar():
        logger.info("Bot iniciado! Capturando estado...")

        # Captura若干截图 para análise
        for i in range(3):
            bot.capturar_pagina()
            time.sleep(5)
            logger.info(f"Captura {i+1}/3")

        logger.info("Dados extraídos. Verifique os arquivos debug_* para análise.")
    else:
        logger.error("Falha ao iniciar bot.")

    bot.fechar()


if __name__ == "__main__":
    main()
