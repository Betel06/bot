"""Map UI do Huntera - encontra todos os elementos clicaveis."""
import os, sys, json, time, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from playwright.sync_api import sync_playwright

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "huntera_session.json")
GAME_URL = "https://huntera.com.br/game"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_map")
os.makedirs(OUT, exist_ok=True)

JS_FIND_ALL = """() => {
    const res = [];
    const seen = new Set();
    const walk = (root, depth) => {
        if (depth > 6) return;
        for (const el of root.children) {
            if (!el || seen.has(el)) continue;
            seen.add(el);
            const r = el.getBoundingClientRect();
            if (r.width < 3 || r.height < 3) { walk(el, depth+1); continue; }
            const txt = (el.textContent || '').trim().substring(0, 60);
            if (txt && txt.length > 0 && txt.length < 60) {
                const key = el.tagName + ':' + Math.round(r.x) + ',' + Math.round(r.y);
                if (!seen.has(key)) {
                    seen.add(key);
                    res.push({
                        tag: el.tagName,
                        text: txt,
                        x: Math.round(r.x + r.width/2),
                        y: Math.round(r.y + r.height/2),
                        w: Math.round(r.width),
                        h: Math.round(r.height),
                    });
                }
            }
            walk(el, depth+1);
        }
    };
    walk(document.body, 0);
    return res;
}"""

def dump_ui(page, nome):
    body = page.inner_text("body")
    with open(os.path.join(OUT, nome + "_text.txt"), "w", encoding="utf-8") as f:
        f.write(body)
    page.screenshot(path=os.path.join(OUT, nome + ".png"))

    elements = page.evaluate(JS_FIND_ALL)
    with open(os.path.join(OUT, nome + "_elements.json"), "w", encoding="utf-8") as f:
        json.dump(elements, f, indent=2, ensure_ascii=False)

    logging.info("[%s] %d elementos", nome, len(elements))
    for el in elements:
        logging.info("  %s '%s' (%d,%d) %dx%d", el["tag"], el["text"][:40], el["x"], el["y"], el["w"], el["h"])

    return body, elements

def click_text(page, text, timeout=3):
    try:
        loc = page.locator("text=" + text).first
        if loc.is_visible(timeout=timeout * 1000):
            loc.click()
            logging.info("Clicou: %s", text)
            return True
    except Exception as e:
        logging.debug("Nao achou '%s': %s", text, e)
    return False

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
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
    page = ctx.new_page()

    logging.info("Navegando pro jogo...")
    page.goto(GAME_URL, wait_until="networkidle", timeout=45000)
    time.sleep(3)

    body, _ = dump_ui(page, "01_charselect")

    if "Escolha seu personagem" in body or "Choose your character" in body:
        for label in ["Jogar", "Play"]:
            if click_text(page, "button:" + label):
                break
        time.sleep(8)

    body, _ = dump_ui(page, "02_game_loaded")
    time.sleep(5)
    body, _ = dump_ui(page, "03_game_ready")

    botoes = ["Caçar", "Prey", "Personagem", "DESPACHAR LOOT", "SAIR DA CAÇADA",
              "Opções", "Amigos", "Guild", "Wiki", "Ranking"]

    for btn in botoes:
        logging.info("--- Tentando: %s ---", btn)
        if click_text(page, btn):
            time.sleep(3)
            dump_ui(page, "04_" + btn.replace(" ", "_").replace("ã","a").replace("ç","c").lower())
            page.keyboard.press("Escape")
            time.sleep(1)

    logging.info("Testando teclado: 1-5, F1-F3, space...")
    for key in ["1", "2", "3", "4", "5", "F1", "F2", "F3", "Space"]:
        page.keyboard.press(key)
        time.sleep(0.5)
    time.sleep(2)
    dump_ui(page, "05_after_keys")

    storage2 = ctx.storage_state()
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(storage2, f, indent=2)

    browser.close()
    pw.stop()
    logging.info("Mapeamento completo!")

if __name__ == "__main__":
    main()
