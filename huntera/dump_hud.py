"""Dump all HUD elements with class names."""
import sys, json, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

with open('huntera_session.json', 'r') as f:
    storage = json.load(f)

pw = sync_playwright().start()
b = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu', '--single-process'])
ctx = b.new_context(storage_state=storage, viewport={'width': 1280, 'height': 800})
pg = ctx.new_page()
pg.goto('https://huntera.com.br/game', wait_until='domcontentloaded', timeout=30000)
time.sleep(15)

body = pg.inner_text('body')
if 'Escolha' in body or 'SUA CONTA' in body:
    try:
        pg.locator('button:has-text("Jogar")').first.click()
    except:
        pass
    time.sleep(10)

# Dump all HUD elements
result = pg.evaluate("""() => {
    const r = [];
    const sels = [
        '[class*="hud"]', '[class*="hp"]', '[class*="mana"]',
        '[class*="life"]', '[class*="health"]', '[class*="bar"]',
        '[class*="stat"]', '[class*="vital"]', '[class*="character"]',
        '[class*="player"]', '[class*="info"]', '[class*="level"]',
        '[class*="exp"]', '[class*="capacity"]', '[class*="weight"]'
    ];
    const seen = new Set();
    sels.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            if (seen.has(el)) return;
            seen.add(el);
            const rc = el.getBoundingClientRect();
            if (rc.width > 0 && rc.height > 0 && rc.width < 500) {
                r.push({
                    tag: el.tagName,
                    cls: (el.className || '').toString().substring(0, 120),
                    text: (el.textContent || '').trim().substring(0, 80),
                    x: Math.round(rc.x),
                    y: Math.round(rc.y),
                    w: Math.round(rc.width),
                    h: Math.round(rc.height)
                });
            }
        });
    });
    return r;
}""")

result2 = pg.evaluate("""() => {
    const r = [];
    document.querySelectorAll('div, span, p').forEach(el => {
        const rc = el.getBoundingClientRect();
        if (rc.y > 550 && rc.width > 0 && rc.height > 0 && rc.width < 400) {
            const txt = (el.textContent || '').trim();
            if (txt.length > 0 && txt.length < 100) {
                r.push({
                    tag: el.tagName,
                    cls: (el.className || '').toString().substring(0, 100),
                    text: txt.substring(0, 80),
                    x: Math.round(rc.x),
                    y: Math.round(rc.y),
                    w: Math.round(rc.width),
                    h: Math.round(rc.height)
                });
            }
        }
    });
    return r;
}""")

with open('hud_dump.txt', 'w', encoding='utf-8') as outf:
    for e in result:
        outf.write("%s.%s '%s' (%d,%d) %dx%d\n" % (e['tag'], e['cls'][:60], e['text'][:50], e['x'], e['y'], e['w'], e['h']))

    outf.write("\n=== BOTTOM HUD (y > 600) ===\n")
    for e in result2:
        outf.write("%s.%s '%s' (%d,%d) %dx%d\n" % (e['tag'], e['cls'][:60], e['text'][:50], e['x'], e['y'], e['w'], e['h']))

print("DONE")
b.close()
pw.stop()
