"""Deep HP/MP debug - tries every approach to read real values."""
import sys, json, time
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
    try: pg.locator('button:has-text("Jogar")').first.click()
    except: pass
    time.sleep(10)

# === Test 1: CSS bar width ===
result = pg.evaluate("""() => {
    var out = {};
    
    // HP bar
    var hpBar = document.querySelector('div.hud-bar.hud-hp');
    var mpBar = document.querySelector('div.hud-bar.hud-mp');
    
    if (hpBar) {
        var hpStyle = window.getComputedStyle(hpBar);
        var hpSpan = hpBar.querySelector('span');
        out.hp_bar = {
            text: hpSpan ? hpSpan.textContent : 'no-span',
            width: hpStyle.width,
            maxWidth: hpStyle.maxWidth,
            innerWidth: hpBar.style.width,
            bgSize: hpStyle.backgroundSize,
            bgPos: hpStyle.backgroundPosition,
            childCount: hpBar.children.length,
            innerHTML: hpBar.innerHTML.substring(0, 200),
            allAttrs: Array.from(hpBar.attributes).map(a => a.name + '=' + a.value),
            dataset: JSON.stringify(hpBar.dataset),
        };
    }
    if (mpBar) {
        var mpStyle = window.getComputedStyle(mpBar);
        var mpSpan = mpBar.querySelector('span');
        out.mp_bar = {
            text: mpSpan ? mpSpan.textContent : 'no-span',
            width: mpStyle.width,
            maxWidth: mpStyle.maxWidth,
            innerWidth: mpBar.style.width,
            bgSize: mpStyle.backgroundSize,
            bgPos: mpStyle.backgroundPosition,
            innerHTML: mpBar.innerHTML.substring(0, 200),
            allAttrs: Array.from(mpBar.attributes).map(a => a.name + '=' + a.value),
            dataset: JSON.stringify(mpBar.dataset),
        };
    }
    
    // Test 2: CSS custom properties
    var root = document.documentElement;
    var rootStyle = window.getComputedStyle(root);
    out.css_vars = {};
    try {
        for (var sheet of document.styleSheets) {
            try {
                for (var rule of sheet.cssRules) {
                    if (rule.selectorText === ':root') {
                        for (var prop of rule.style) {
                            if (prop.startsWith('--')) {
                                var val = rule.style.getPropertyValue(prop);
                                if (val.indexOf('hp') >= 0 || val.indexOf('life') >= 0 || 
                                    val.indexOf('mp') >= 0 || val.indexOf('mana') >= 0 ||
                                    prop.indexOf('hp') >= 0 || prop.indexOf('mp') >= 0 ||
                                    prop.indexOf('life') >= 0 || prop.indexOf('mana') >= 0) {
                                    out.css_vars[prop] = val;
                                }
                            }
                        }
                    }
                }
            } catch(e) {}
        }
    } catch(e) { out.css_error = e.message; }
    
    // Test 3: localStorage / sessionStorage
    out.localStorage = {};
    out.sessionStorage = {};
    try {
        for (var i = 0; i < localStorage.length; i++) {
            var k = localStorage.key(i);
            var kl = k.toLowerCase();
            if (kl.indexOf('hp') >= 0 || kl.indexOf('life') >= 0 || kl.indexOf('mp') >= 0 || 
                kl.indexOf('mana') >= 0 || kl.indexOf('player') >= 0 || kl.indexOf('char') >= 0 ||
                kl.indexOf('stats') >= 0 || kl.indexOf('health') >= 0) {
                out.localStorage[k] = localStorage.getItem(k).substring(0, 200);
            }
        }
        for (var i = 0; i < sessionStorage.length; i++) {
            var k = sessionStorage.key(i);
            var kl = k.toLowerCase();
            if (kl.indexOf('hp') >= 0 || kl.indexOf('life') >= 0 || kl.indexOf('mp') >= 0 || 
                kl.indexOf('mana') >= 0 || kl.indexOf('player') >= 0 || kl.indexOf('char') >= 0) {
                out.sessionStorage[k] = sessionStorage.getItem(k).substring(0, 200);
            }
        }
    } catch(e) {}
    
    // Test 4: All elements with 'hp' or 'mp' in class/id
    out.hp_mp_elements = [];
    document.querySelectorAll('[class*="hp"], [class*="mp"], [class*="life"], [class*="mana"], [id*="hp"], [id*="mp"]').forEach(function(el) {
        var r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            out.hp_mp_elements.push({
                tag: el.tagName,
                cls: el.className.toString().substring(0, 100),
                id: el.id,
                text: (el.textContent || '').substring(0, 50).trim(),
                w: Math.round(r.width), h: Math.round(r.height),
                x: Math.round(r.x), y: Math.round(r.y),
                dataHP: el.dataset.hp || '',
                dataMP: el.dataset.mp || '',
                allData: JSON.stringify(el.dataset),
            });
        }
    });
    
    // Test 5: Angular components
    var gameShell = document.querySelector('app-game-shell');
    if (gameShell) {
        var ngCtx = gameShell['__ngContext__'];
        out.ng_shell = {
            exists: true,
            ctx_type: typeof ngCtx,
            ctx_len: Array.isArray(ngCtx) ? ngCtx.length : 'not-array',
        };
        if (Array.isArray(ngCtx)) {
            out.ng_items_with_hp = [];
            for (var i = 0; i < Math.min(ngCtx.length, 100); i++) {
                var item = ngCtx[i];
                if (item && typeof item === 'object') {
                    try {
                        var keys = Object.keys(item);
                        var hpKeys = keys.filter(k => k.toLowerCase().includes('hp') || k.toLowerCase().includes('life') || k.toLowerCase().includes('health'));
                        var mpKeys = keys.filter(k => k.toLowerCase().includes('mp') || k.toLowerCase().includes('mana'));
                        if (hpKeys.length > 0 || mpKeys.length > 0) {
                            var obj = {};
                            hpKeys.forEach(k => obj[k] = typeof item[k] === 'function' ? 'fn' : item[k]);
                            mpKeys.forEach(k => obj[k] = typeof item[k] === 'function' ? 'fn' : item[k]);
                            out.ng_items_with_hp.push({ index: i, keys: obj });
                        }
                    } catch(e) {}
                }
            }
        }
    }
    
    return out;
}""")

with open('hp_debug.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("DONE")
b.close()
pw.stop()
