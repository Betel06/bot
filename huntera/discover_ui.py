"""Descobre a UI do jogo Huntera - roda 1 vez e salva tudo."""
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright

SESSION_FILE = os.path.join(os.path.dirname(__file__), "huntera_session.json")
GAME_URL = "https://huntera.com.br/game"
OUT = os.path.dirname(__file__)

def discover():
    with open(SESSION_FILE, "r") as f:
        storage = json.load(f)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(
        storage_state=storage,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
    page = ctx.new_page()

    print("[1] Navegando pro jogo...")
    page.goto(GAME_URL, wait_until="networkidle", timeout=30000)
    time.sleep(3)
    page.screenshot(path=os.path.join(OUT, "disc_01_charselect.png"))
    print(f"    URL: {page.url}")
    print(f"    Texto: {page.inner_text('body')[:300]}")

    # Clica Jogar
    print("[2] Clicando 'Jogar'...")
    jogar = page.query_selector('button:has-text("Jogar")')
    if jogar:
        jogar.click()
        print("    Clicou Jogar!")
        time.sleep(5)
    else:
        print("    Botao Jogar NAO encontrado!")

    page.screenshot(path=os.path.join(OUT, "disc_02_game.png"))
    print(f"    URL: {page.url}")

    # Captura o HTML inteiro da pagina do jogo
    html = page.content()
    with open(os.path.join(OUT, "disc_game_html.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    HTML salvo ({len(html)} bytes)")

    # Captura texto visivel
    body = page.inner_text("body")
    with open(os.path.join(OUT, "disc_game_text.txt"), "w", encoding="utf-8") as f:
        f.write(body)
    print(f"    Texto: {body[:500]}")

    # Captura todos os botoes clicaveis
    print("[3] Listando botoes/links...")
    elements = page.evaluate("""() => {
        const res = [];
        document.querySelectorAll('button, a, [role="button"], [onclick], [class*="btn"], [class*="button"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                res.push({
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 80),
                    classes: el.className.toString().substring(0, 120),
                    id: el.id,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                });
            }
        });
        return res;
    }""")
    with open(os.path.join(OUT, "disc_buttons.json"), "w") as f:
        json.dump(elements, f, indent=2, ensure_ascii=False)
    print(f"    {len(elements)} botoes encontrados")
    for el in elements:
        print(f"    [{el['tag']}] '{el['text'][:40]}' ({el['x']},{el['y']}) cls={el['classes'][:60]}")

    # Captura localStorage
    print("[4] Capturando localStorage...")
    ls = page.evaluate("""() => {
        const r = {};
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            r[k] = localStorage.getItem(k);
        }
        return r;
    }""")
    with open(os.path.join(OUT, "disc_localstorage.json"), "w") as f:
        json.dump(ls, f, indent=2, ensure_ascii=False)
    print(f"    Keys: {list(ls.keys())[:20]}")

    # Espera mais e captura mais screenshots
    print("[5] Aguardando 15s e capturando de novo...")
    time.sleep(15)
    page.screenshot(path=os.path.join(OUT, "disc_03_after15s.png"))
    body2 = page.inner_text("body")
    with open(os.path.join(OUT, "disc_game_text2.txt"), "w", encoding="utf-8") as f:
        f.write(body2)
    print(f"    Texto 2: {body2[:500]}")

    elements2 = page.evaluate("""() => {
        const res = [];
        document.querySelectorAll('button, a, [role="button"], [onclick], [class*="btn"], [class*="button"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                res.push({
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 80),
                    classes: el.className.toString().substring(0, 120),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                });
            }
        });
        return res;
    }""")
    with open(os.path.join(OUT, "disc_buttons2.json"), "w") as f:
        json.dump(elements2, f, indent=2, ensure_ascii=False)
    print(f"    {len(elements2)} botoes (depois de 15s)")
    for el in elements2:
        print(f"    [{el['tag']}] '{el['text'][:40]}' ({el['x']},{el['y']}) cls={el['classes'][:60]}")

    # Captura HTML de novo
    html2 = page.content()
    with open(os.path.join(OUT, "disc_game_html2.html"), "w", encoding="utf-8") as f:
        f.write(html2)

    # Salva session atualizada
    storage2 = ctx.storage_state()
    with open(SESSION_FILE, "w") as f:
        json.dump(storage2, f, indent=2)
    print("    Session atualizada!")

    browser.close()
    pw.stop()
    print("OK!")

if __name__ == "__main__":
    discover()
