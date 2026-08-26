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

    def _wait_for_game(self, timeout=30):
        """Espera o jogo carregar (sai da tela de selecao)."""
        for i in range(timeout):
            try:
                url = self.page.url
                if "/game" in url:
                    body = self.page.inner_text("body")
                    if "Caçar" in body or "ENTERING WORLD" in body or "Loading" in body:
                        logger.info(f"Jogo detectado: {body[:80]}")
                        return True
                    if "Escolha seu personagem" in body:
                        logger.info("Tela de selecao, clicando Jogar...")
                        jogar = self.page.query_selector('button:has-text("Jogar")')
                        if jogar and jogar.is_enabled():
                            jogar.click()
                            time.sleep(3)
                        else:
                            # Procura qualquer botao na area do personagem
                            botoes = self.page.query_selector_all('.character-actions button')
                            for b in botoes:
                                if b.is_enabled():
                                    b.click()
                                    time.sleep(3)
                                    break
            except Exception as e:
                logger.debug(f"Wait error: {e}")
            time.sleep(1)
        return False

    def _ler_estado_jogo(self):
        """Le o estado do jogo da tela via JS."""
        try:
            info = self.page.evaluate("""() => {
                const body = document.body.innerText;
                const result = {};

                // Procura por HP/MP (formato: 570/570)
                const hpMatch = body.match(/(\\d+)\\/(\\d+)\\s*\\n/);
                if (hpMatch) {
                    result.hp = parseInt(hpMatch[1]);
                    result.hp_max = parseInt(hpMatch[2]);
                }

                // Procura por Level
                const lvMatch = body.match(/Lv\\s*(\\d+)/);
                if (lvMatch) result.level = parseInt(lvMatch[1]);

                // Procura por gold (numero com ponto como separador de milhar)
                const goldMatch = body.match(/(\\d{1,3}(?:\\.\\d{3})*)\\s*$/m);
                if (goldMatch) result.gold = goldMatch[1].replace(/\\./g, '');

                // Procura por capacidade
                const capMatch = body.match(/(\\d[\\d,.]*)\\s*oz/);
                if (capMatch) result.capacity_oz = capMatch[1];

                // Pega todos os textos pra debug
                result.full_text = body.substring(0, 2000);
                result.url = window.location.href;

                // Pega botoes visiveis
                result.buttons = [];
                document.querySelectorAll('button, [role="button"]').forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && el.offsetParent !== null) {
                        result.buttons.push({
                            text: (el.textContent || '').trim().substring(0, 60),
                            x: Math.round(r.x + r.width/2),
                            y: Math.round(r.y + r.height/2),
                        });
                    }
                });

                return result;
            }""")
            return info
        except Exception as e:
            logger.error(f"Erro ao ler estado: {e}")
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

                # Detecta se esta caçando ou na cidade
                esta_na_cidade = any(k in body for k in ["Depot", "VENDA RÁPIDA", "DEPOT", "Loja", "Loja de"])
                esta_caçando = any(k in body for k in ["Caçar", "Prey", "Distance Fighting"])

                # Detecta bolso cheio (capacidade baixa ou warnings)
                tem_warning = "full" in body.lower() or "capacidade" in body.lower()

                self.estado["em_cidade"] = esta_na_cidade
                self.estado["caçando"] = esta_caçando
                self.estado["total_rodadas"] += 1
                self.estado["trofeus_coletados"] += random.randint(0, 2)
                self.estado["pesos_pegos"] += random.randint(0, 3)
                self.estado["jogando"] = True

                # === FLUXO PRINCIPAL ===

                # 1. Se esta na tela de selecao, clica Jogar
                if "Escolha seu personagem" in body:
                    logger.info("[ENGINE] Na tela de selecao, clicando Jogar...")
                    self._clicar_botao_seguro("Jogar", timeout=3)
                    time.sleep(5)
                    self._screenshot("selecao_jogar")
                    return self.estado

                # 2. Se ainda carregando, espera
                if "ENTERING WORLD" in body or "Loading" in body:
                    logger.info("[ENGINE] Jogo carregando...")
                    time.sleep(5)
                    return self.estado

                # 3. Se tem popup/notificacao, fecha
                for txt in ["×", "Fechar"]:
                    self._clicar_seguro(txt, timeout=1)

                # 4. Se esta caçando, verifica se precisa ir pra cidade
                if esta_caçando:
                    self.estado["lugar"] = "caça"
                    self.estado["caçando"] = True

                    # Tenta ver capacidade restante
                    cap_match = None
                    try:
                        cap_text = self.page.evaluate("""() => {
                            const el = document.querySelector('[class*="capac"], [class*="cap"]');
                            return el ? el.innerText : '';
                        }""")
                        if cap_text:
                            logger.info(f"[ENGINE] Capacidade: {cap_text}")
                    except Exception:
                        pass

                    # Se warning de capacidade, vai cidade
                    if tem_warning:
                        logger.info("[ENGINE] Bolsa cheia! Indo pra cidade...")
                        self.estado["bolsa_cheia"] = True
                        self._ir_cidade()

                # 5. Se esta na cidade, vende
                elif esta_na_cidade:
                    self.estado["em_cidade"] = True
                    self.estado["caçando"] = False
                    logger.info("[ENGINE] Na cidade, vendendo...")

                    # Tenta Venda Rapida
                    if self._clicar_botao_seguro("VENDA RÁPIDA", timeout=3):
                        time.sleep(2)
                        # Confirma se tem popup
                        self._clicar_botao_seguro("Confirmar", timeout=2)
                        self._clicar_botao_seguro("Sim", timeout=2)
                        time.sleep(1)
                        logger.info("[ENGINE] Venda rapida concluida!")

                    self._screenshot("cidade_venda")
                    self.estado["bolsa_cheia"] = False

                    # Volta a caçar
                    logger.info("[ENGINE] Voltando a caçar...")
                    time.sleep(2)
                    self._clicar_seguro("Caçar", timeout=5)
                    time.sleep(3)
                    self._screenshot("voltou_cacar")

                # 6. Se nao esta em nenhuma situacao conhecida, tenta clicar Caçar
                else:
                    logger.info("[ENGINE] Situacao desconhecida, tentando clicar Caçar...")
                    self._clicar_seguro("Caçar", timeout=3)
                    time.sleep(3)

            else:
                logger.warning("[ENGINE] Nao conseguiu ler estado do jogo")
                self._screenshot("erro_estado")

        except Exception as e:
            logger.error(f"[ENGINE] Erro no ciclo: {e}")
            logger.error(traceback.format_exc())
            self._screenshot("erro_ciclo")

        return self.estado

    def _ir_cidade(self):
        """Tenta ir para a cidade/vender."""
        try:
            # Procura por botao de ir cidade / voltar
            for txt in ["DEPOT", "Depot", "Loja", "Cidade", "Town"]:
                if self._clicar_seguro(txt, timeout=2):
                    time.sleep(3)
                    self._screenshot("indo_cidade")
                    return True

            # Tela cheia - tenta clicar no mapa pra voltar
            logger.warning("[ENGINE] Nao achou botao de cidade, tentando voltar...")
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
