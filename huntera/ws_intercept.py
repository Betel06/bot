"""Intercept WebSocket messages to find real HP/MP from server."""
import sys, json, time
from playwright.sync_api import sync_playwright

with open('huntera_session.json', 'r') as f:
    storage = json.load(f)

ws_messages = []

def on_ws(ws):
    def on_msg(msg):
        try:
            text = msg if isinstance(msg, str) else str(msg)
            ws_messages.append(text[:500])
        except: pass
    ws.on("framereceived", on_msg)
    ws.on("framesent", on_msg)

pw = sync_playwright().start()
b = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu', '--single-process'])
ctx = b.new_context(storage_state=storage, viewport={'width': 1280, 'height': 800})
pg = ctx.new_page()
pg.on("websocket", on_ws)

pg.goto('https://huntera.com.br/game', wait_until='domcontentloaded', timeout=30000)
time.sleep(15)
body = pg.inner_text('body')
if 'Escolha' in body or 'SUA CONTA' in body:
    try: pg.locator('button:has-text("Jogar")').first.click()
    except: pass
    time.sleep(10)

# Wait for WS messages
time.sleep(15)

# Save WS messages
with open('ws_messages.txt', 'w', encoding='utf-8') as f:
    for i, msg in enumerate(ws_messages):
        f.write(f"MSG {i}: {msg}\n\n")

# Also try to force game tick by running JS
result = pg.evaluate("""() => {
    var out = {};
    
    // Force animation frame
    if (window.requestAnimationFrame) {
        window.requestAnimationFrame(() => {});
    }
    
    // Check if game has WebSocket open
    out.ws_urls = [];
    // Check performance entries for WS
    var entries = performance.getEntriesByType('resource');
    entries.forEach(function(e) {
        if (e.name.indexOf('ws') >= 0 || e.name.indexOf('socket') >= 0) {
            out.ws_urls.push(e.name);
        }
    });
    
    // Check for Angular NgZone / change detection
    var appRoot = document.querySelector('app-root');
    if (appRoot) {
        try {
            var ng = window.ng;
            if (ng) {
                out.ng_exists = true;
                var comp = ng.getComponent(appRoot);
                if (comp) {
                    out.ng_comp = Object.keys(comp).slice(0, 20);
                }
            }
        } catch(e) { out.ng_error = e.message; }
        
        // Try Angular's __ngContext__ deeper
        var shell = document.querySelector('app-game-shell');
        if (shell) {
            var ctx = shell['__ngContext__'];
            out.shell_ctx_type = typeof ctx;
            if (typeof ctx === 'number') {
                // It's an index into LView - need to find the LView
                out.shell_ctx_is_index = true;
                // Try to find LView in Angular internals
                try {
                    var lView = null;
                    // Angular stores LView in __ngContext__ on the host element
                    // It's usually at the element level
                    var allNg = document.querySelectorAll('[__ngcontext__]');
                    out.ng_context_count = allNg.length;
                } catch(e2) {}
            }
        }
    }
    
    // Check for any global game state variables
    var candidates = ['player', 'gameState', 'character', 'hero', 'avatar', 'me', 'self'];
    candidates.forEach(function(k) {
        if (window[k] !== undefined) {
            try {
                var v = window[k];
                if (typeof v === 'object' && v !== null) {
                    out['global_' + k] = Object.keys(v).slice(0, 30);
                    // Check for hp/life
                    if (v.hp !== undefined) out['global_' + k + '_hp'] = v.hp;
                    if (v.life !== undefined) out['global_' + k + '_life'] = v.life;
                    if (v.health !== undefined) out['global_' + k + '_health'] = v.health;
                }
            } catch(e) {}
        }
    });
    
    // Force update by dispatching events
    document.dispatchEvent(new Event('mousemove'));
    document.dispatchEvent(new Event('keydown'));
    
    // Read fill widths again after forcing
    var hpBar = document.querySelector('div.hud-bar.hud-hp');
    var mpBar = document.querySelector('div.hud-bar.hud-mp');
    if (hpBar) {
        var fill = hpBar.querySelector('.fill');
        out.hp_fill_after = fill ? fill.style.width : 'no-fill';
        out.hp_span_after = hpBar.querySelector('span') ? hpBar.querySelector('span').textContent : 'no-span';
    }
    if (mpBar) {
        var fill = mpBar.querySelector('.fill');
        out.mp_fill_after = fill ? fill.style.width : 'no-fill';
        out.mp_span_after = mpBar.querySelector('span') ? mpBar.querySelector('span').textContent : 'no-span';
    }
    
    return out;
}""")

with open('ws_debug.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"DONE - {len(ws_messages)} WS messages captured")
b.close()
pw.stop()
