"""
HUNTERA BOT ENGINE v3 - Joga de verdade via Playwright com seletores CSS reais.
"""
import os
import re
import sys
import json
import time
import random
import logging
import threading
import traceback

logger = logging.getLogger("huntera_engine")

HUNTERA_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.environ.get("HUNTERA_SESSION_PATH",
    os.path.join(HUNTERA_DIR, "huntera_session.json"))
# Sessao estendida: cookies de TODOS os dominios (inclui Gmail/Google).
# Mantem o email logado no navegador do bot entre execucoes.
BROWSER_SESSION_FILE = os.environ.get("HUNTERA_BROWSER_SESSION",
    os.path.join(HUNTERA_DIR, "browser_session.json"))
RAILWAY_SESSION = "/etc/secrets/huntera_session.json"
GAME_URL = "https://huntera.com.br/game"
SCREENSHOT_DIR = os.path.join(HUNTERA_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

from huntera_config import (
    CAÇAS, CAPACIDADE_MAX, DISPATCH_INTERVALO_SEGUNDOS, DISPATCH_LIMITE_PCT,
    CACADA_FIXA, TIER_CACADA,
)

# CSS selectors reais do jogo
SEL = {
    "dispatch_btn": "button.hud-hunt-quick-sell",
    "dispatch_group": "div.hud-dispatch-group",
    "leave_hunt_btn": "button.hud-leave-hunt",
    "hunt_details_btn": "button.hud-hunt-details",
    "city_actions": "div.hud-city-actions",
    "bag_inventory": "button.hud-bag-inventory",
    "slot": "button.hud-slot.assigned",
    "cyclopedia_close": "button:has-text('Fechar')",
    "popup_close": "button:has-text('×')",
    "sidebar_hunt": "span:text-is('Caçar')",
    "sidebar_menu": "button:has-text('Menu')",
}


class HunteraBot:
    def __init__(self, callback_estado=None):
        self.browser = None
        self.context = None
        self.page = None
        self.running = False
        self.logado = False
        self.callback_estado = callback_estado
        self.estado = {
            "modo": "caça",
            "personagem": "UnOrdinary",
            "level": 0,
            "hp": 0,
            "hp_max": 0,
            "mp": 0,
            "mp_max": 0,
            "gold": 0,
            "capacity_oz": 0.0,
            "lugar": "desconhecido",
            "caçando": False,
            "em_cidade": False,
            "total_rodadas": 0,
            "dispatch_timer": time.time(),
            "pocoes_usadas": 0,
            "dispatches_feitos": 0,
            "ultimo_update": None,
            "caçada_atual": None,
            "paralisado": False,
            "status_msg": "",
            "abertas": 0,
            "encerradas": 0,
        }
        self._pw = None
        self._lock = threading.Lock()

    def _start_pw(self):
        if self._pw is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
        return self._pw

    def _load_session(self):
        # 1) Sessao estendida do navegador do bot (todos os dominios, inclui Gmail) tem prioridade
        for path in [BROWSER_SESSION_FILE, RAILWAY_SESSION, SESSION_FILE]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("cookies"):
                        logger.info("Sessao: %s (%d cookies)", path, len(data["cookies"]))
                        return data
                except Exception as e:
                    logger.error("Erro sessao %s: %s", path, e)
        return None

    def _save_browser_session(self):
        """Salva cookies de todos os dominios (inclui Gmail) na sessao estendida."""
        try:
            if not self.context:
                return
            cookies = self.context.cookies()
            if cookies:
                with open(BROWSER_SESSION_FILE, "w", encoding="utf-8") as f:
                    json.dump({"cookies": cookies}, f)
                logger.info("Sessao navegador salva: %d cookies (dominios ok)", len(cookies))
        except Exception as e:
            logger.error("Erro salvar sessao navegador: %s", e)

    def _screenshot(self, nome):
        try:
            self.page.screenshot(path=os.path.join(SCREENSHOT_DIR, "%s.png" % nome))
        except Exception:
            pass

    def _ler_estado_jogo(self):
        """Le HP, MP, level, capacity, caçada e botoes via JS."""
        try:
            info = self.page.evaluate(r"""() => {
                const body = document.body ? document.body.innerText : '';
                const result = {};
                result.full_text = body.substring(0, 5000);
                result.url = window.location.href;

                var lvMatch = body.match(/Lv\s*(\d+)/i);
                if (lvMatch) result.level = parseInt(lvMatch[1]);

                // HP/MP: le fill div width (source of truth) + texto
                var hpBar = document.querySelector('div.hud-bar.hud-hp');
                var mpBar = document.querySelector('div.hud-bar.hud-mp');
                
                // HP bar: fill div width = % real de HP
                if (hpBar) {
                    var hpFill = hpBar.querySelector('.fill');
                    var hpSpan = hpBar.querySelector('span');
                    if (hpSpan) {
                        var hm = hpSpan.textContent.trim().match(/(\d+)\/(\d+)/);
                        if (hm) { result.hp = parseInt(hm[1]); result.hp_max = parseInt(hm[2]); }
                    }
                    if (hpFill) {
                        var w = hpFill.style.width;
                        if (w && w.indexOf('%') >= 0) {
                            result.hp_fill_pct = parseFloat(w);
                            // Calcula HP real do fill % * max
                            if (result.hp_max > 0) {
                                result.hp = Math.round(result.hp_fill_pct / 100 * result.hp_max);
                            }
                        }
                    }
                }
                
                // MP bar: fill div width = % real de MP
                if (mpBar) {
                    var mpFill = mpBar.querySelector('.fill');
                    var mpSpan = mpBar.querySelector('span');
                    if (mpSpan) {
                        var mm = mpSpan.textContent.trim().match(/(\d+)\/(\d+)/);
                        if (mm) { result.mp = parseInt(mm[1]); result.mp_max = parseInt(mm[2]); }
                    }
                    if (mpFill) {
                        var w = mpFill.style.width;
                        if (w && w.indexOf('%') >= 0) {
                            result.mp_fill_pct = parseFloat(w);
                            if (result.mp_max > 0) {
                                result.mp = Math.round(result.mp_fill_pct / 100 * result.mp_max);
                            }
                        }
                    }
                }

                // Capacity via CSS selector
                var capEl = document.querySelector('div.inventory-capacity');
                result.capacity_blocked = false;
                if (capEl) {
                    var capText = capEl.textContent;
                    var capMatch = capText.match(/([\d,.]+)\s*oz/);
                    if (capMatch) result.capacity_oz = parseFloat(capMatch[1].replace(',', '.'));
                    // Mochila cheia: classe capacity-blocked (capacidade livre quase zero)
                    if (capEl.className && capEl.className.indexOf('capacity-blocked') >= 0) {
                        result.capacity_blocked = true;
                    }
                }
                // Tambem detecta toast de "sem capacidade para carregar"
                if (body.indexOf('capacidade para carregar') >= 0 || body.indexOf('Capacidade para carregar') >= 0) {
                    result.capacity_blocked = true;
                }

                // Gold
                var goldMatch = body.match(/([\d.]+)\nLoja/);
                if (goldMatch) result.gold = parseInt(goldMatch[1].replace(/\./g, ''));

                result.paralisado = body.toLowerCase().indexOf('paralisado') >= 0;

                // HUD buttons
                result.hud_buttons = [];
                var sels = [
                    'button.hud-hunt-quick-sell',
                    'button.hud-leave-hunt',
                    'button.hud-hunt-details',
                    'div.hud-city-actions button',
                    'button.hud-slot.assigned'
                ];
                sels.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        var r = el.getBoundingClientRect();
                        if (r.width > 5 && r.height > 5) {
                            result.hud_buttons.push({
                                sel: sel,
                                text: (el.textContent || '').trim().substring(0, 40),
                                x: Math.round(r.x + r.width / 2),
                                y: Math.round(r.y + r.height / 2),
                                cls: (el.className || '').toString().substring(0, 100)
                            });
                        }
                    });
                });

                result.cyclopedia_open = !!document.querySelector('.cyclopedia-window');
                return result;
            }""")
            return info
        except Exception as e:
            logger.error("Erro ler estado: %s", e)
            return None

    def _clicar_css(self, selector, timeout=3):
        """Clica em elemento por CSS selector."""
        try:
            loc = self.page.locator(selector).first
            if loc.is_visible(timeout=timeout * 1000):
                loc.click()
                return True
        except Exception:
            pass
        return False

    def _clicar_texto(self, texto, timeout=3):
        """Clica em elemento por texto visivel."""
        try:
            loc = self.page.locator("text=" + texto).first
            if loc.is_visible(timeout=timeout * 1000):
                loc.click()
                return True
        except Exception:
            pass
        return False

    def _clicar_botao(self, texto, timeout=3):
        """Clica em <button> por texto."""
        try:
            loc = self.page.locator('button:has-text("%s")' % texto).first
            if loc.is_visible(timeout=timeout * 1000):
                loc.click()
                return True
        except Exception:
            pass
        return False

    def _pressionar(self, key):
        try:
            self.page.keyboard.press(key)
            return True
        except Exception:
            return False

    def _fechar_popups(self):
        """Fecha Cyclopedia, Server Save popup, etc."""
        # Cyclopedia
        if self._clicar_css(".cyclopedia-window button:has-text('×')", timeout=1):
            logger.info("[POPUP] Fechou Cyclopedia")
            time.sleep(1)
        # Server Save popup
        for txt in ["Fechar", "Close", "×"]:
            if self._clicar_botao(txt, timeout=1):
                logger.info("[POPUP] Fechou: %s", txt)
                time.sleep(0.5)

    def _iniciar(self, visivel=False):
        """Inicia browser e loga. visivel=True abre janela para acompanhar."""
        storage = self._load_session()
        if not storage:
            return False

        pw = self._start_pw()
        logger.info("Iniciando navegador (%s)...", "VISIVEL" if visivel else "headless")
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-extensions",
            "--no-first-run",
        ]
        if not visivel:
            args += ["--disable-gpu", "--single-process"]
        self.browser = pw.chromium.launch(
            headless=not visivel,
            args=args,
        )
        self.context = self.browser.new_context(
            storage_state=storage,
            viewport={"width": 1360, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        self.context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        self.page = self.context.new_page()
        self.running = True

        logger.info("Navegando pro jogo...")
        try:
            self.page.goto(GAME_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("Aviso: %s", e)
        time.sleep(5)
        self._screenshot("01_inicio")

        # Espera jogo e clica Play
        for _ in range(40):
            try:
                body = self.page.inner_text("body")
                if "Caçar" in body or "Hunt" in body or "Distance Fighting" in body:
                    logger.info("Jogo carregado!")
                    self.logado = True
                    break
                if "Escolha seu personagem" in body or "SUA CONTA" in body:
                    for label in ["Jogar", "Play"]:
                        if self._clicar_botao(label, timeout=3):
                            time.sleep(6)
                            break
                elif "ENTERING WORLD" in body:
                    logger.info("Entrando no mundo...")
            except Exception:
                pass
            time.sleep(1)

        self._screenshot("02_jogo")
        self._fechar_popups()
        self.logado = True
        self._save_browser_session()
        return True

    def _atualizar_estado(self, info):
        if not info:
            return
        body = info.get("full_text", "")

        # Level (fix: persistia 0)
        if info.get("level"):
            self.estado["level"] = info["level"]

        # HP/MP via CSS bar fill (source of truth)
        if info.get("hp_fill_pct") is not None:
            # Calculate hp from fill percentage if we have hp_max
            hp_max = info.get("hp_max")
            if hp_max:
                self.estado["hp"] = round(info["hp_fill_pct"] / 100 * hp_max)
                self.estado["hp_max"] = hp_max
            else:
                # Fallback to span text if no hp_max
                if info.get("hp"):
                    self.estado["hp"] = info["hp"]
        elif info.get("hp") is not None:
            # Use hp directly from span text
            self.estado["hp"] = info["hp"]
        
        if info.get("hp_max") is not None:
            self.estado["hp_max"] = info["hp_max"]
        
        # MP via CSS bar fill (source of truth)
        if info.get("mp_fill_pct") is not None:
            mp_max = info.get("mp_max")
            if mp_max:
                self.estado["mp"] = round(info["mp_fill_pct"] / 100 * mp_max)
                self.estado["mp_max"] = mp_max
            else:
                if info.get("mp"):
                    self.estado["mp"] = info["mp"]
        elif info.get("mp") is not None:
            self.estado["mp"] = info["mp"]
        
        if info.get("mp_max") is not None:
            self.estado["mp_max"] = info["mp_max"]
        if info.get("gold"):
            self.estado["gold"] = info["gold"]
        if info.get("capacity_oz"):
            self.estado["capacity_oz"] = info["capacity_oz"]
        self.estado["mochila_cheia"] = bool(info.get("capacity_blocked", False))
        self.estado["paralisado"] = info.get("paralisado", False)

        # Detecta caçada atual
        for nome in CAÇAS:
            if nome.lower() in body.lower():
                self.estado["caçada_atual"] = nome
                break

        # Detecta se tem loot pra vender (botao com has-item = tem loot na bolsa)
        hud = info.get("hud_buttons", [])
        self.estado["tem_loot"] = any("has-item" in b.get("cls", "") for b in hud)

        self.estado["ultimo_update"] = time.strftime("%Y-%m-%d %H:%M:%S")

        # Historico de HP curto para detectar char morto/travado
        hp_pct = self._hp_pct()
        hist = self.estado.setdefault("_hp_hist", [])
        hist.append(hp_pct)
        if len(hist) > 10:
            hist.pop(0)
        self.estado["_hp_zero_seguidos"] = sum(1 for h in hist[-5:] if h <= 0)
        self.estado["_hp_full_seguidos"] = sum(1 for h in hist[-5:] if h >= 100)

    def _detectar_estado(self, body, info):
        na_selecao = any(k in body for k in [
            "Escolha seu personagem", "SUA CONTA", "Choose your character"
        ])

        hud = info.get("hud_buttons", [])
        cls_all = " ".join(b.get("cls", "") for b in hud).lower()
        sel_all = " ".join(b.get("sel", "") for b in hud).lower()

        # Caçando: presenca de botao de acao da hunt (detail/leave/quick-sell da hunt).
        # IMPORTANTE: os botoes da hunt TAMBEM tem classe hud-city-action, entao o que
        # distingue caçando de cidade e o sufixo hud-hunt-action.
        caçando = "hud-hunt-action" in cls_all
        # Cidade: tem acoes de cidade (depot/quick-sell/imbue/temple) mas NAO esta caçando
        em_cidade = (not caçando and "hud-city-action" in sel_all
                     and any(k in cls_all for k in ["hud-depot", "hud-quick-sell", "hud-imbue", "hud-temple"]))
        carregando = "ENTERING WORLD" in body and "Caçar" not in body

        return {
            "na_selecao": na_selecao,
            "caçando": caçando,
            "em_cidade": em_cidade,
            "carregando": carregando,
        }

    def _hp_pct(self):
        if self.estado["hp_max"] > 0:
            return int(self.estado["hp"] * 100 / self.estado["hp_max"])
        return 100

    def _mp_pct(self):
        if self.estado["mp_max"] > 0:
            return int(self.estado["mp"] * 100 / self.estado["mp_max"])
        return 100

    # === ACOES REAIS DO JOGO ===

    def _acao_dispatch(self):
        """Clica Despachar loot e confirma."""
        logger.info("[ACTION] Dispatchando loot...")

        # Fecha popups primeiro (Cyclopedia pode cobrir)
        self._acao_fechar_popups()
        time.sleep(1)

        cap_antes = self.estado["capacity_oz"]

        # 1. Tenta clicar no botao real detectado pelo JS (posicao/conteudo + classe)
        alvo = self._localizar_botao_dispatch()
        if alvo:
            ok = self._clicar_botao_dispatch(alvo)
        else:
            ok = False

        if ok and self._acao_confirma_dispatch(cap_antes):
            return True

        logger.warning("[ACTION] Dispatch nao confirmado")
        self._screenshot("dispatch_falhou")
        return False

    def _acao_vender_cidade(self):
        """Na cidade: clica em 'Venda rapida' pra vender o loot da bolsa."""
        logger.info("[ACTION] Na cidade, vendendo loot...")
        self._acao_fechar_popups()
        time.sleep(1)
        # Botao da cidade: Venda rapida
        if self._clicar_css_valid("button.hud-city-action.hud-quick-sell", timeout=3):
            time.sleep(2)
            self._confirmar_venda_cidade()
            return True
        if self._clicar_texto("Venda rápida", timeout=3) or self._clicar_texto("Venda rapida", timeout=2):
            time.sleep(2)
            self._confirmar_venda_cidade()
            return True
        logger.warning("[ACTION] Nao achou Venda rapida na cidade")
        return False

    def _confirmar_venda_cidade(self):
        """Confirma a venda (modal possivel: Enviar/Sim/Confirmar/OK)."""
        for conf in ["Enviar", "Vender", "Confirmar", "Sim", "Yes", "OK"]:
            if self._clicar_botao(conf, timeout=2):
                time.sleep(2)
                logger.info("[ACTION] Venda cidade confirmada: %s", conf)
                self.estado["dispatches_feitos"] += 1
                self.estado["dispatch_timer"] = time.time()
                return True
        logger.info("[ACTION] Venda cidade (sem modal de confirmacao)")
        self.estado["dispatches_feitos"] += 1
        self.estado["dispatch_timer"] = time.time()
        return True

    def _acao_vender_indo_cidade(self):
        """Mochila cheia: sai da caçada, vai pra cidade, vende tudo (Venda rapida), volta a farmar."""
        logger.info("[ACTION] Mochila cheia -> indo pra cidade vender...")
        # 1. Sai da caçada
        self._acao_sair_cacada()
        time.sleep(4)
        # 2. Espera chegar na cidade (ate 240s - transicao e variavel, 3s a ~4min)
        # Loop leve: so confere o botao de Venda rapida / cidade (sem fechar popups a cada iter).
        chegou = False
        for i in range(240):
            time.sleep(1)
            if self._em_cidade_agora():
                chegou = True
                break
            if i % 20 == 0:
                logger.info("[ACTION] esperando chegar na cidade... (%ds)", i)
        if not chegou:
            logger.warning("[ACTION] Nao detectou cidade apos sair da caçada")
            self._screenshot("cidade_nao_detectada")
        # 3. Vende tudo
        self._acao_vender_cidade()
        time.sleep(2)
        # 4. Volta pra caçada
        nova = self._melhor_cacada()
        self._acao_entrar_cacada(nova)
        self.estado["dispatch_cooldown_timer"] = time.time()
        self.estado["dispatch_cooldown"] = 60
        return True

    def _em_cidade_agora(self):
        """Verifica (lendo o estado atual) se o personagem esta na cidade."""
        try:
            info = self._ler_estado_jogo()
            if not info:
                return False
            body = info.get("full_text", "")
            hud = info.get("hud_buttons", [])
            cls_all = " ".join(b.get("cls", "") for b in hud).lower()
            sel_all = " ".join(b.get("sel", "") for b in hud).lower()
            cacando = "hud-hunt-action" in cls_all
            em_cidade = (not cacando and "hud-city-action" in sel_all
                         and any(k in cls_all for k in ["hud-depot", "hud-quick-sell", "hud-imbue", "hud-temple"]))
            return em_cidade
        except Exception:
            return False

    def _localizar_botao_dispatch(self):
        """Procura o botao de dispatch na varredura JS (hud_buttons)."""
        try:
            info = self._ler_estado_jogo()
            if not info:
                return None
            hud = info.get("hud_buttons", [])
            for b in hud:
                if "quick-sell" in b.get("sel", "") and "has-item" in b.get("cls", ""):
                    return b
            # Fallback: qualquer quick-sell visivel
            for b in hud:
                if "quick-sell" in b.get("sel", ""):
                    return b
        except Exception:
            pass
        return None

    def _clicar_css_valid(self, selector, timeout=3):
        """Igual _clicar_css mas so conta se o elemento existe de verdade."""
        try:
            loc = self.page.locator(selector).first
            if loc.is_visible(timeout=timeout * 1000):
                loc.click()
                return True
        except Exception:
            pass
        return False

    def _clicar_botao_dispatch(self, botao):
        """Clica no botao de dispatch (por CSS/coordenada detectada)."""
        try:
            if self._clicar_css("button.hud-hunt-quick-sell", timeout=3):
                time.sleep(2)
                return True
            # Usa a coordenada real detectada em vez de magica
            if botao.get("x") and botao.get("y"):
                self.page.mouse.click(botao["x"], botao["y"])
                time.sleep(2)
                return True
        except Exception:
            pass
        return False

    def _acao_confirma_dispatch(self, cap_antes):
        """Confirma dispatch apos clicar no botao. So conta sucesso se capacity baixar."""
        for conf in ["Enviar", "Sim", "Yes", "Confirmar", "OK"]:
            if self._clicar_botao(conf, timeout=3):
                time.sleep(2)
                return self._registrar_dispatch(cap_antes)
        # Sem botao de confirmacao: verifica se capacity realmente baixou
        return self._registrar_dispatch(cap_antes)

    def _registrar_dispatch(self, cap_antes):
        """Registra dispatch so se capacidade realmente baixou (evita falso-positivo)."""
        novo_info = None
        try:
            novo_info = self._ler_estado_jogo()
        except Exception:
            pass
        cap_depois = novo_info.get("capacity_oz") if novo_info and novo_info.get("capacity_oz") else cap_antes
        if cap_depois < cap_antes - 1:
            self.estado["dispatches_feitos"] += 1
            self.estado["dispatch_timer"] = time.time()
            self.estado["dispatch_cooldown_timer"] = time.time()
            logger.info("[ACTION] Dispatch OK! CAP %.0f -> %.0f (total: %d)",
                        cap_antes, cap_depois, self.estado["dispatches_feitos"])
            self._screenshot("dispatch_ok")
            return True
        # Capacity nao mudou - NAO conta como sucesso
        logger.warning("[ACTION] Dispatch nao confirmado (CAP %.0f -> %.0f)", cap_antes, cap_depois)
        self.estado["dispatch_cooldown_timer"] = time.time()
        self.estado["dispatch_cooldown"] = 30
        return False

    def _acao_sair_cacada(self):
        """Sai da caçada (leva o char de volta pra cidade em ~3s)."""
        logger.info("[ACTION] Saindo da caçada...")
        self._acao_fechar_popups()
        if self._clicar_css(SEL["leave_hunt_btn"], timeout=5):
            time.sleep(3)
            self._screenshot("saiu_cacada")
            return True
        if self._clicar_texto("Sair da caçada", timeout=3):
            time.sleep(3)
            return True
        return False

    def _acao_fechar_popups(self):
        """Fecha todos os popups."""
        self._fechar_popups()
        # Fecha.Server Save / Welcome
        self._clicar_botao("Fechar", timeout=1)
        time.sleep(0.5)

    def _acao_usar_pocao(self, tipo="hp"):
        """Usa pocao via hotbar (1=hp, 2=mp)."""
        tecla = "1" if tipo == "hp" else "2"
        if self._pressionar(tecla):
            self.estado["pocoes_usadas"] += 1

    def _acao_entrar_cacada(self, nome):
        """Entra numa caçada abrindo o modal via #nav-start-hunt e clicando na entrada."""
        logger.info("[ACTION] Entrando na caçada: %s (tier=%s)", nome, TIER_CACADA)
        self._acao_fechar_popups()
        # Abre modal de caçada
        if not self._clicar_css("#nav-start-hunt", timeout=4):
            if not self._clicar_texto("Caçar", timeout=3):
                logger.warning("[ACTION] Nao abriu menu de caçada")
                self._screenshot("abrir_cacada_falha")
                return False
        time.sleep(3)
        # Seleciona o lugar pelo nome (busca no button.hunt-entry por startswith do copy)
        if not self._selecionar_lugar_js(nome):
            # Fallback: busca por substring no modal aberto
            if not self._selecionar_lugar_js(nome, substring=True):
                logger.warning("[ACTION] Nao achou lugar '%s' no modal", nome)
                self._screenshot("lugar_nao_achado")
                return False
        time.sleep(2)
        # Seleciona o tier (Cauteloso/Ousado/Agressivo), se aplicavel
        if TIER_CACADA:
            self._selecionar_tier(TIER_CACADA)
        # Clica em "Iniciar caçada"
        if self._clicar_css("#hunt-start", timeout=4):
            time.sleep(5)
            self.estado["ultima_cacada_entrada"] = nome
            self.estado["caçada_atual"] = nome
            logger.info("[ACTION] Iniciou caçada: %s", nome)
            return True
        logger.warning("[ACTION] Nao achou botao Iniciar (nome=%s)", nome)
        return False

    def _selecionar_lugar_js(self, nome, substring=False):
        """Clica no button.hunt-entry cujo texto de copy começa com (ou contem) nome."""
        try:
            achou = self.page.evaluate(
                r"""(args) => {
                    const [nome, substring] = args;
                    const alvo = (nome || '').toLowerCase().trim();
                    let els = Array.from(document.querySelectorAll('button.hunt-entry'));
                    // o copy vira o nome concatenado com o monstro; compara inicio da string
                    const match = (t) => substring
                        ? t.toLowerCase().indexOf(alvo) === 0
                        : t.toLowerCase().startsWith(alvo);
                    let el = null;
                    for (const b of els) {
                        const c = b.querySelector('.hunt-entry-copy');
                        const t = (c ? c.textContent : b.textContent) || '';
                        if (match(t)) { el = b; break; }
                    }
                    if (!el) return false;
                    el.click();
                    return true;
                }""",
                [nome, substring],
            )
            if achou:
                logger.info("[ACTION] Selecionou lugar '%s' (substring=%s)", nome, substring)
            return bool(achou)
        except Exception as e:
            logger.error("[ACTION] Erro _selecionar_lugar_js: %s", e)
            return False

    def _selecionar_tier(self, tier):
        """Clica no botao de tier da caçada (Cauteloso/Ousado/Agressivo)."""
        if not tier:
            return False
        try:
            ok = False
            for b in self.page.query_selector_all("button.hunt-tier"):
                t = (b.text_content() or "").strip()
                if t == tier:
                    b.click()
                    ok = True
                    break
            if ok:
                logger.info("[ACTION] Tier %s selecionado", tier)
            else:
                # Fallback por coordenada conhecida: Cauteloso/Ousado/Agressivo
                coords = {"Cauteloso": (726, 408), "Ousado": (873, 408), "Agressivo": (726, 446)}
                if tier in coords:
                    x, y = coords[tier]
                    self.page.mouse.click(x, y)
                    logger.info("[ACTION] Tier %s (coordenada)", tier)
            time.sleep(1)
            return True
        except Exception as e:
            logger.error("[ACTION] Erro _selecionar_tier: %s", e)
            return False

    def _melhor_cacada(self):
        """Retorna a caçada fixa (se configurada) ou a melhor pro level."""
        if CACADA_FIXA and CACADA_FIXA in CAÇAS:
            return CACADA_FIXA
        level = self.estado["level"]
        melhor = None
        melhor_lvl = 0
        for nome, cfg in CAÇAS.items():
            lvl_min = cfg.get("level_min", 0)
            if level >= lvl_min and lvl_min > melhor_lvl:
                melhor = nome
                melhor_lvl = lvl_min
        return melhor or list(CAÇAS.keys())[0]

    def iniciar(self, visivel=False):
        return self._iniciar(visivel=visivel)

    def rodar_ciclo(self):
        """1 ciclo do jogo real."""
        if not self.running or not self.page:
            return self.estado

        try:
            info = self._ler_estado_jogo()
            if not info:
                logger.warning("Nao leu estado")
                return self.estado

            self._atualizar_estado(info)
            body = info.get("full_text", "")
            self.estado["total_rodadas"] += 1

            est = self._detectar_estado(body, info)
            self.estado["caçando"] = est["caçando"]
            self.estado["em_cidade"] = est["em_cidade"]

            # Log detalhado
            if self.estado["total_rodadas"] % 10 == 0:
                logger.info(
                    "[Ciclo %d] LV=%d HP=%d/%d (%d%%) MP=%d/%d (%d%%) CAP=%.0f "
                    "caçando=%s/%s loot=%s dispatches=%d pocoes=%d",
                    self.estado["total_rodadas"],
                    self.estado["level"], self.estado["hp"], self.estado["hp_max"], self._hp_pct(),
                    self.estado["mp"], self.estado["mp_max"], self._mp_pct(),
                    self.estado["capacity_oz"],
                    est["caçando"], self.estado["caçada_atual"],
                    self.estado.get("tem_loot", False),
                    self.estado["dispatches_feitos"], self.estado["pocoes_usadas"]
                )
                # Dump body lines com "/" pra debug parser
                lines = body.split('\n')
                for idx, l in enumerate(lines):
                    l = l.strip()
                    if '/' in l and len(l) < 20 and any(c.isdigit() for c in l):
                        ctx = lines[max(0,idx-1):min(len(lines),idx+2)]
                        logger.info("  BODY L%d: [%s] ctx=%s", idx, l, [x.strip() for x in ctx])

            # === FLUXO ===

            # 1. Tela selecao
            if est["na_selecao"]:
                for label in ["Jogar", "Play"]:
                    if self._clicar_botao(label, timeout=3):
                        break
                time.sleep(6)
                return self.estado

            # 2. Carregando
            if est["carregando"]:
                time.sleep(5)
                return self.estado

            # 3. Fecha popups primeiro
            self._acao_fechar_popups()

            # 4. CAÇANDO - a logica principal
            if est["caçando"]:
                hp = self._hp_pct()
                mp = self._mp_pct()

                # 4a. MORTE/DESCONEXAO: HP 0 por varios ciclos seguidos = char morto/travado
                # NAO gastar pocoes com char morto - avisa e tenta sair da caçada pra respawn
                if hp <= 0 and self.estado.get("_hp_zero_seguidos", 0) >= 3:
                    logger.warning("[ACTION] HP 0%% por %d ciclos - char possivelmente morto/travado. Nao usa pocao.",
                                   self.estado.get("_hp_zero_seguidos", 0))
                    self.estado["status_msg"] = "morto/travado"
                    if self.estado["total_rodadas"] % 40 == 0:
                        self._screenshot("morto")
                    # Tenta sair da caçada para respawnar (sem gastar pocao)
                    if self.estado["total_rodadas"] % 15 == 0:
                        self._acao_sair_cacada()
                        time.sleep(3)
                        self._acao_entrar_cacada(self._melhor_cacada())
                    return self.estado

                # 4b. HP baixo (vivo) -> pocao
                if 0 < hp < 70:
                    logger.info("[ACTION] HP %d%% -> pocao", hp)
                    self._acao_usar_pocao("hp")
                    time.sleep(1)
                    self._acao_usar_pocao("hp")
                    time.sleep(0.5)
                else:
                    self.estado["status_msg"] = ""

                # 4c. MP baixo -> pocao
                if mp < 50 and mp > 0:
                    logger.info("[ACTION] MP %d%% -> pocao", mp)
                    self._acao_usar_pocao("mp")
                    time.sleep(1)

                # 4d. Mochila cheia -> ir na cidade vender tudo e voltar
                cap = self.estado["capacity_oz"]
                agora = time.time()

                # Cooldown apos ultima ida a cidade (evita repetir a cada ciclo)
                dispatch_cooldown = self.estado.setdefault("dispatch_cooldown", 90)
                timer_from_dispatch = agora - self.estado.get("dispatch_cooldown_timer", 0)
                em_cooldown = timer_from_dispatch < dispatch_cooldown

                # Mochila cheia (capacity-blocked/toast) OU acima do limite e fora de cooldown -> vai vender
                mochila_cheia = self.estado.get("mochila_cheia", False)
                if (mochila_cheia or cap > CAPACIDADE_MAX * (DISPATCH_LIMITE_PCT / 100.0)) and not em_cooldown:
                    logger.info("[ACTION] Mochila cheia=%s cap=%.0f -> ir a cidade vender", mochila_cheia, cap)
                    self._acao_vender_indo_cidade()
                    self.estado["dispatch_cooldown_timer"] = agora
                    self.estado["dispatch_cooldown"] = 90

                # 4e. Troca caçada se a fixa for diferente da atual (ou a cada 300 ciclos)
                nova = self._melhor_cacada()
                entrado = self.estado.get("ultima_cacada_entrada")
                trocar = nova and nova != entrado
                if trocar and CACADA_FIXA:
                    # Caçada fixa configurada: troca enquanto nao estiver nela (debounce p/ nao repetir)
                    agora = time.time()
                    ultimo = self.estado.get("troca_timer", 0)
                    if agora - ultimo > 60:
                        logger.info("[ACTION] Caçada fixa %s != entrado %s - trocando agora",
                                    nova, entrado)
                        self.estado["troca_timer"] = agora
                        self._acao_sair_cacada()
                        time.sleep(3)
                        self._acao_entrar_cacada(nova)
                elif self.estado["total_rodadas"] % 300 == 0:
                    if nova and nova != entrado:
                        logger.info("[ACTION] Trocando: %s -> %s", entrado, nova)
                        self._acao_sair_cacada()
                        time.sleep(3)
                        self._acao_entrar_cacada(nova)

            # 5. NA CIDADE
            elif est["em_cidade"]:
                logger.info("[ACTION] Na cidade")
                # Vende o loot (Venda rapida) se tiver item
                if self.estado.get("tem_loot", False):
                    self._acao_vender_cidade()
                    time.sleep(2)
                # Volta pra caçada
                nova = self._melhor_cacada()
                self._acao_entrar_cacada(nova)
                time.sleep(5)

            # 6. Desconhecido
            else:
                if self.estado["total_rodadas"] % 20 == 0:
                    logger.warning("[ACTION] Estado estranho: %s", body[:100])
                    self._screenshot("estranho")
                self._acao_fechar_popups()
                # Tenta voltar
                for label in ["Caçar", "Hunt", "Play", "Jogar"]:
                    if self._clicar_texto(label, timeout=2):
                        time.sleep(3)
                        break

        except Exception as e:
            err = str(e)
            logger.error("[ENGINE] Erro: %s", err[:200])
            if "crashed" in err.lower() or "target closed" in err.lower():
                logger.warning("[ENGINE] CHROMIUM CRASHOU!")
                self._reiniciar_browser()
            else:
                self._screenshot("erro_ciclo")

        return self.estado

    def _reiniciar_browser(self):
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            time.sleep(5)
            self._iniciar()
            logger.info("[ENGINE] Browser reiniciado!")
        except Exception as e:
            logger.error("[ENGINE] Falha reinicio: %s", e)

    def fechar(self):
        self.running = False
        try:
            if self.context:
                storage = self.context.storage_state()
                with open(SESSION_FILE, "w", encoding="utf-8") as f:
                    json.dump(storage, f, indent=2, ensure_ascii=False)
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
        logger.info("Bot iniciado! Rodando...")
        for i in range(60):
            e = bot.rodar_ciclo()
            if i % 5 == 0:
                logger.info("Ciclo %d: LV=%d HP=%d/%d MP=%d/%d CAP=%.0f",
                    i+1, e["level"], e["hp"], e["hp_max"],
                    e["mp"], e["mp_max"], e["capacity_oz"])
            time.sleep(8)
    else:
        logger.error("Falha ao iniciar")
    bot.fechar()


if __name__ == "__main__":
    main()
