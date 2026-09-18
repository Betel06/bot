"""Testa dispatch e'autres interacoes especificas."""
import os, sys, json, time, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from playwright.sync_api import sync_playwright

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "huntera_session.json")
GAME_URL = "https://huntera.com.br/game"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_map")
os.makedirs(OUT, exist_ok=True)

def main():
    with open(SESSION_FILE, "r") as f:
        storage = json.load(f)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=[
        "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
        "--disable-web-security", "--single-process",
    ])
    ctx = browser.new_context(
        storage_state=storage,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
    page = ctx.new_page()

    page.goto(GAME_URL, wait_until="networkidle", timeout=45000)
    time.sleep(3)

    body = page.inner_text("body")
    if "Escolha seu personagem" in body or "SUA CONTA" in body:
        for label in ["Jogar", "Play"]:
            try:
                el = page.locator('button:has-text("%s")' % label).first
                if el.is_visible(timeout=3000):
                    el.click()
                    break
            except: pass
        time.sleep(8)

    time.sleep(5)
    body = page.inner_text("body")

    # Procura "DESPACHAR" de varias formas
    logging.info("=== PROCURANDO DESPACHAR ===")

    # 1. Procura por texto contendo "despachar" (case insensitive)
    result = page.evaluate("""() => {
        const res = [];
        const body = document.body ? document.body.innerText : '';
        const idx = body.toLowerCase().indexOf('despachar');
        if (idx >= 0) {
            res.push('TEXT FOUND: ' + body.substring(idx - 20, idx + 50));
        }

        // Procura todos os elementos com texto contendo 'despachar'
        const walk = (root, depth) => {
            if (depth > 8) return;
            for (const el of root.children) {
                if (!el) continue;
                const txt = (el.textContent || '').toLowerCase();
                if (txt.includes('despachar')) {
                    const r = el.getBoundingClientRect();
                    res.push(el.tagName + ': "' + el.textContent.trim().substring(0, 80) + '" (' +
                        Math.round(r.x) + ',' + Math.round(r.y) + ') ' +
                        Math.round(r.width) + 'x' + Math.round(r.height) +
                        ' cls=' + (el.className || '').toString().substring(0, 60));
                }
                walk(el, depth + 1);
            }
        };
        walk(document.body, 0);
        return res;
    }""")
    for r in result:
        logging.info("  %s", r)

    # 2. Procura por classe CSS do jogo
    logging.info("=== PROCURANDO CLASSES DO JOGO ===")
    result2 = page.evaluate("""() => {
        const res = [];
        document.querySelectorAll('[class*="dispatch"], [class*="loot"], [class*="sell"], [class*="bag"], [class*="inventory"], [class*="hunt"], [class*="action-bar"], [class*="slot"]').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                res.push(el.tagName + '.' + (el.className || '').toString().substring(0, 80) +
                    ': "' + (el.textContent || '').trim().substring(0, 60) + '"' +
                    ' (' + Math.round(r.x) + ',' + Math.round(r.y) + ') ' +
                    Math.round(r.width) + 'x' + Math.round(r.height));
            }
        });
        return res;
    }""")
    for r in result2[:30]:
        logging.info("  %s", r)

    # 3. Procura todos os elementos clicaveis do jogo (navegando toda a DOM)
    logging.info("=== TODOS OS ELEMENTOS COM TEXTO (depth 10) ===")
    result3 = page.evaluate("""() => {
        const res = [];
        const seen = new Set();
        const walk = (root, depth) => {
            if (depth > 10) return;
            for (const el of root.children) {
                if (!el || seen.has(el)) continue;
                seen.add(el);
                const txt = (el.textContent || '').trim();
                const ownTxt = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join(' ').trim();
                if (ownTxt && ownTxt.length > 0 && ownTxt.length < 80) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        res.push({
                            tag: el.tagName,
                            text: ownTxt,
                            x: Math.round(r.x + r.width/2),
                            y: Math.round(r.y + r.height/2),
                            w: Math.round(r.width),
                            h: Math.round(r.height),
                        });
                    }
                }
                walk(el, depth + 1);
            }
        };
        walk(document.body, 0);
        return res;
    }""")

    logging.info("Encontrou %d elementos com texto proprio", len(result3))
    for el in result3:
        if any(k in el["text"].lower() for k in ["despachar", "sair", "caça", "depot", "venda", "loot", "hunt", "exit"]):
            logging.info("  >> %s '%s' (%d,%d) %dx%d", el["tag"], el["text"], el["x"], el["y"], el["w"], el["h"])

    # Salva todos
    with open(os.path.join(OUT, "all_text_elements.json"), "w", encoding="utf-8") as f:
        json.dump(result3, f, indent=2, ensure_ascii=False)

    # 4. Testa dispatch via coordenada - clica em todas as posicoes onde "DESPACHAR" aparece
    logging.info("=== TENTANDO CLICK POR COORDENADAS ===")
    for el in result3:
        if "despachar" in el["text"].lower() or "dispatch" in el["text"].lower():
            logging.info("Clicando em (%d, %d): %s", el["x"], el["y"], el["text"])
            page.mouse.click(el["x"], el["y"])
            time.sleep(3)
            page.screenshot(path=os.path.join(OUT, "after_dispatch_click.png"))
            body2 = page.inner_text("body")
            logging.info("Body apos click: %s", body2[:200])
            # Procura botao de confirmacao
            for conf in ["Sim", "Yes", "Confirmar", "Confirm", "OK", "Enviar"]:
                try:
                    loc = page.locator('button:has-text("%s")' % conf).first
                    if loc.is_visible(timeout=2000):
                        logging.info("Encontrou confirmacao: %s", conf)
                        loc.click()
                        time.sleep(2)
                        break
                except: pass
            break

    # 5. Procura "SAIR DA CACADA"
    logging.info("=== PROCURANDO SAIR DA CACADA ===")
    for el in result3:
        if "sair" in el["text"].lower() or "exit" in el["text"].lower():
            logging.info("  >> %s '%s' (%d,%d) %dx%d", el["tag"], el["text"], el["x"], el["y"], el["w"], el["h"])

    # 6. Testa teclas do jogo
    logging.info("=== TESTANDO TECLAS ===")
    for key in ["1", "2", "3", "4", "5", "6", "7", "8"]:
        page.keyboard.press(key)
        time.sleep(0.3)
    time.sleep(1)
    page.screenshot(path=os.path.join(OUT, "after_hotkeys.png"))

    storage2 = ctx.storage_state()
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(storage2, f, indent=2)

    browser.close()
    pw.stop()
    logging.info("OK!")

if __name__ == "__main__":
    main()
