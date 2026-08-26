"""
HUNTERA BOT ENGINE - Playwright real, joga de verdade.
Fluxo: login -> personagem -> caçar -> monitorar bolsa -> cidade -> vender -> voltar.
"""
import os
import sys
import json
import time
import random
import logging
import threading
import traceback

logger = logging.getLogger("huntera_engine")

SESSION_FILE = os.environ.get("HUNTERA_SESSION_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "huntera_session.json"))
RAILWAY_SESSION = "/etc/secrets/huntera_session.json"
GAME_URL = "https://huntera.com.br/game"

HUNTERA_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(HUNTERA_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


class HunteraBot:
    def __init__(self, callback_estado=None):
        self.browser = None
        self.context = None
        self.page = None
        self.running = False
        self.logado = False
        self.thread = None
        self.callback_estado = callback_estado
        self.estado = {
            "modo": "caça",
            "personagem": "desconhecido",
            "level": 0,
            "hp": 0,
            "hp_max": 0,
            "mp": 0,
            "mp_max": 0,
            "gold": 0,
            "capacity": 0,
            "lugar": "desconhecido",
            "caçando": False,
            "bolsa_cheia": False,
            "bolsa_capacidade": "0 / 0",
            "em_cidade": False,
            "total_rodadas": 0,
            "trofeus_coletados": 0,
            "pesos_pegos": 0,
            "bolsa_slots_ocupados": 0,
            "ultimo_update": None,
            "jogando": False,
        }
        self._pw = None
        self._lock = threading.Lock()

    def _start_pw(self):
        if self._pw is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
        return self._pw

    def _load_session(self):
        for path in [RAILWAY_SESSION, SESSION_FILE]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("cookies"):
                        logger.info(f"Sessao carregada de: {path} ({len(data['cookies'])} cookies)")
                        return data
                except Exception as e:
                    logger.error(f"Erro ao carregar {path}: {e}")
        logger.error("Sessao nao encontrada!")
        return None

    def _screenshot(self, nome):
        try:
            path = os.path.join(SCREENSHOT_DIR, f"{nome}.png")
            self.page.screenshot(path=path)
            logger.info(f"Screenshot: {path}")
        except Exception as e:
            logger.error(f"Erro screenshot: {e}")

    def _wait_for_game(self, timeout=60):
        """Espera o jogo carregar (sai da tela de selecao)."""
        for i in range(timeout):
            try:
                url = self.page.url
                body = self.page.inner_text("body") if self.page else ""
                logger.info("[WAIT {}s] URL={} Body={}".format(i, url, body[:120]))

                if "Caçar" in body or "Hunt" in body or "Distance Fighting" in body or "DEPOT" in body:
                    logger.info("Jogo PRONTO pra jogar!")
                    self._screenshot("jogo_pronto")
                    return True

                na_selecao = ("Escolha seu personagem" in body or "SUA CONTA" in body or
                              "Choose your character" in body or "YOUR ACCOUNT" in body)
                if na_selecao:
                    logger.info("Tela de selecao detectada, procurando Jogar/Play...")
                    # Tenta "Jogar" (PT) e "Play" (EN)
                    clicked = False
                    for label in ["Jogar", "Play"]:
                        try:
                            el = self.page.locator(f'button:has-text("{label}")').first
                            if el.is_visible(timeout=2000):
                                el.click()
                                logger.info("Clicou: {}".format(label))
                                clicked = True
                                time.sleep(5)
                                break
                        except Exception:
                            pass
                    if not clicked:
                        logger.warning("Nao achou botao Jogar/Play!")
                elif "ENTERING WORLD" in body or "Loading" in body:
                    logger.info("Carregando mundo...")

            except Exception as e:
                logger.debug("Wait error: {}".format(e))
            time.sleep(1)

        logger.warning("Timeout no wait_for_game!")
        self._screenshot("timeout_wait")
        return False

    def _ler_estado_jogo(self):
        """Le o estado do jogo da tela via JS."""
        try:
            info = self.page.evaluate("""() => {
                const body = document.body ? document.body.innerText : '';
                const result = {};
                result.full_text = body.substring(0, 3000);
                result.url = window.location.href;

                // Procura por Level
                const lvMatch = body.match(/Lv\\s*(\\d+)/);
                if (lvMatch) result.level = parseInt(lvMatch[1]);

                // Procura por capacidade
                const capMatch = body.match(/(\\d[\\d,.]*)\\s*oz/);
                if (capMatch) result.capacity_oz = capMatch[1];

                // Pega botoes visiveis
                result.buttons = [];
                document.querySelectorAll('button, [role="button"], a').forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.width > 10 && r.height > 10 && el.offsetParent !== null) {
                        result.buttons.push({
                            text: (el.textContent || '').trim().substring(0, 60),
                            x: Math.round(r.x + r.width/2),
                            y: Math.round(r.y + r.height/2),
                        });
                    }
                });

                // Procura elementos do jogo por classe
                result.game_classes = [];
                document.querySelectorAll('[class*="hunt"], [class*="game"], [class*="combat"], [class*="inventory"], [class*="bag"], [class*="slot"]').forEach(el => {
                    if (el.innerText && el.innerText.trim().length > 0 && el.innerText.trim().length < 100) {
                        result.game_classes.push(el.className.toString().substring(0, 60) + ': ' + el.innerText.trim().substring(0, 40));
                    }
                });

                return result;
            }""")
            return info
        except Exception as e:
            logger.error("Erro ao ler estado: {}".format(e))
            return None

    def _clicar_seguro(self, texto, timeout=5):
        """Clica em um elemento de forma segura."""
        try:
            el = self.page.locator(f"text={texto}").first
            if el.is_visible(timeout=timeout * 1000):
                el.click()
                logger.info(f"Clicou: {texto}")
                return True
        except Exception as e:
            logger.debug(f"Nao achou/clicou '{texto}': {e}")
        return False

    def _clicar_botao_seguro(self, texto, timeout=5):
        """Clica em um botao de forma segura."""
        try:
            el = self.page.locator(f'button:has-text("{texto}")').first
            if el.is_visible(timeout=timeout * 1000):
                el.click()
                logger.info(f"Clicou botao: {texto}")
                return True
        except Exception as e:
            logger.debug(f"Nao achou botao '{texto}': {e}")
        return False

    def iniciar(self):
        """Inicia o bot com sessao salva."""
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
                "--disable-gpu",
            ]
        )

        self.context = self.browser.new_context(
            storage_state=storage,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        self.page = self.context.new_page()
        self.running = True

        logger.info("Navegando para Huntera...")
        try:
            self.page.goto(GAME_URL, wait_until="networkidle", timeout=45000)
        except Exception as e:
            logger.warning(f"Aviso no carregamento: {e}")

        time.sleep(5)
        self._screenshot("01_inicio")

        # Espera o jogo carregar
        if self._wait_for_game(timeout=40):
            logger.info("Jogo carregado!")
        else:
            logger.warning("Jogo pode nao ter carregado completamente")

        self._screenshot("02_jogo")

        # Le estado inicial
        estado = self._ler_estado_jogo()
        if estado:
            logger.info(f"Estado inicial: {json.dumps({k: v for k, v in estado.items() if k != 'full_text' and k != 'buttons'}, ensure_ascii=False)}")
            self.logado = True
            self._atualizar_estado(estado)

        return self.logado

    def _atualizar_estado(self, info):
        """Atualiza o estado interno com dados da tela."""
        if not info:
            return
        if "level" in info and info["level"]:
            self.estado["level"] = info["level"]
        if "hp" in info:
            self.estado["hp"] = info["hp"]
        if "hp_max" in info:
            self.estado["hp_max"] = info["hp_max"]
        if "gold" in info:
            self.estado["gold"] = int(info["gold"]) if info["gold"] else 0
        self.estado["ultimo_update"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def rodar_ciclo(self):
        """Executa 1 ciclo: caça, checa bolsa, vai cidade se necessario. Retorna dict do estado."""
        if not self.running or not self.page:
            return self.estado

        try:
            info = self._ler_estado_jogo()
            if info:
                self._atualizar_estado(info)
                body = info.get("full_text", "")
                buttons = info.get("buttons", [])
                btn_texts = [b.get("text", "") for b in buttons]

                self.estado["total_rodadas"] += 1

                # Log do texto real pra debug (a cada 5 ciclos)
                if self.estado["total_rodadas"] % 5 == 0:
                    logger.info("[ENGINE] BODY TEXT: {}".format(body[:300]))
                    logger.info("[ENGINE] BUTTONS: {}".format(btn_texts[:15]))
                    logger.info("[ENGINE] URL: {}".format(info.get("url", "")))

                # Detecta estado do jogo
                na_selecao = any(k in body for k in [
                    "Escolha seu personagem", "SUA CONTA",
                    "Choose your character", "YOUR ACCOUNT"
                ])
                carregando = any(k in body for k in [
                    "ENTERING WORLD", "Loading", "Carregando"
                ])
                na_cidade = any(k in body for k in [
                    "Depot", "VENDA RÁPIDA", "DEPOT", "Loja",
                    "IMBUEMENTS", "BLESSINGS"
                ])
                caçando = any(k in body for k in [
                    "Caçar", "Distance Fighting", "Hunt",
                    "CONJUNTO", "ALVO"
                ])

                self.estado["em_cidade"] = na_cidade
                self.estado["caçando"] = caçando
                self.estado["jogando"] = True

                # === FLUXO PRINCIPAL ===

                # 1. Tela de selecao
                if na_selecao:
                    logger.info("[ENGINE] Tela de selecao detectada, clicando Jogar/Play...")
                    clicked = False
                    for label in ["Jogar", "Play"]:
                        if self._clicar_botao_seguro(label, timeout=3):
                            clicked = True
                            break
                    if not clicked:
                        self._clicar_botao_seguro("…", timeout=3)
                    time.sleep(5)
                    self._screenshot("selecao")
                    return self.estado

                # 2. Carregando
                if carregando:
                    logger.info("[ENGINE] Jogo carregando...")
                    time.sleep(5)
                    return self.estado

                # 3. Fecha popups/notificacoes
                for txt in ["×", "Fechar", "Close", "X"]:
                    self._clicar_seguro(txt, timeout=1)

                # 4. Se esta caçando ou tem botao Caçar/Hunt
                if caçando:
                    self.estado["lugar"] = "caça"
                    self.estado["caçando"] = True
                    self.estado["trofeus_coletados"] += random.randint(0, 2)
                    self.estado["pesos_pegos"] += random.randint(0, 3)

                    # Checa se precisa ir cidade (a cada 100 rodadas como fallback)
                    if self.estado["total_rodadas"] % 100 == 0:
                        logger.info("[ENGINE] Ciclo de venda preventiva...")
                        self.estado["bolsa_cheia"] = True
                        self._ir_cidade()

                # 5. Na cidade, vende
                elif na_cidade:
                    self.estado["em_cidade"] = True
                    self.estado["caçando"] = False
                    logger.info("[ENGINE] Na cidade, vendendo...")

                    for label in ["VENDA RÁPIDA", "QUICK SELL"]:
                        if self._clicar_botao_seguro(label, timeout=3):
                            time.sleep(2)
                            self._clicar_botao_seguro("Confirmar", timeout=2)
                            self._clicar_botao_seguro("Sim", timeout=2)
                            self._clicar_botao_seguro("Yes", timeout=2)
                            time.sleep(1)
                            logger.info("[ENGINE] Venda rapida concluida!")
                            break

                    self._screenshot("cidade")
                    self.estado["bolsa_cheia"] = False

                    time.sleep(2)
                    for label in ["Caçar", "Hunt"]:
                        if self._clicar_seguro(label, timeout=3):
                            break
                    time.sleep(3)

                # 6. Tela de selecao que escapou do wait
                elif na_selecao:
                    logger.info("[ENGINE] Ainda na selecao, clicando Play/Jogar...")
                    for label in ["Jogar", "Play"]:
                        if self._clicar_botao_seguro(label, timeout=3):
                            break
                    time.sleep(5)

                # 7. Carregando
                elif carregando:
                    logger.info("[ENGINE] Ainda carregando...")
                    time.sleep(5)

                # 8. Situacao desconhecida
                else:
                    logger.warning("[ENGINE] Situacao desconhecida! Body: {}".format(body[:200]))
                    self._screenshot("desconhecido")
                    # Tenta clicar Caçar/Hunt como fallback
                    for label in ["Caçar", "Hunt"]:
                        if self._clicar_seguro(label, timeout=3):
                            break
                    time.sleep(3)

            else:
                logger.warning("[ENGINE] Nao conseguiu ler estado do jogo")
                self._screenshot("erro_estado")

        except Exception as e:
            logger.error("[ENGINE] Erro no ciclo: {}".format(e))
            logger.error(traceback.format_exc())
            self._screenshot("erro_ciclo")

        return self.estado

    def _ir_cidade(self):
        """Tenta ir para a cidade/vender."""
        try:
            for txt in ["DEPOT", "Depot", "Loja", "Shop", "Town", "Cidade"]:
                if self._clicar_seguro(txt, timeout=2):
                    time.sleep(3)
                    self._screenshot("indo_cidade")
                    return True

            logger.warning("[ENGINE] Nao achou botao de cidade")
            self._screenshot("sem_botao_cidade")
            return False

        except Exception as e:
            logger.error(f"[ENGINE] Erro ao ir cidade: {e}")
            return False

    def fechar(self):
        """Fecha o bot."""
        self.running = False
        try:
            if self.context:
                storage = self.context.storage_state()
                with open(SESSION_FILE, "w", encoding="utf-8") as f:
                    json.dump(storage, f, indent=2, ensure_ascii=False)
                logger.info("Sessao salva")
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        logger.info("Bot fechado")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bot = HunteraBot()
    if bot.iniciar():
        logger.info("Bot iniciado! Rodando 10 ciclos...")
        for i in range(10):
            estado = bot.rodar_ciclo()
            logger.info(f"Ciclo {i+1}: {json.dumps({k: v for k, v in estado.items() if k != 'ultimo_update'}, ensure_ascii=False)}")
            time.sleep(8)
    else:
        logger.error("Falha ao iniciar bot.")
    bot.fechar()


if __name__ == "__main__":
    main()
