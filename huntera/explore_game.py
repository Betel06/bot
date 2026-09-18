"""Explora window.game para achar HP/MP real."""
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
    try:
        pg.locator('button:has-text("Jogar")').first.click()
    except:
        pass
    time.sleep(10)

result = pg.evaluate("""() => {
    var out = {};
    var g = window.game;
    
    // Top-level keys
    out.top_keys = Object.keys(g).slice(0, 50);
    out.game_type = g.constructor ? g.constructor.name : 'unknown';
    
    // Procura player/character
    if (g.player) {
        out.player = {};
        for (var k in g.player) {
            try {
                var v = g.player[k];
                if (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') {
                    out.player[k] = v;
                } else if (v && typeof v === 'object') {
                    out.player[k] = '{obj:' + Object.keys(v).slice(0, 5).join(',') + '}';
                }
            } catch(e) {}
        }
    }
    
    // Procura scene/scenes
    if (g.scene) {
        out.scene_keys = Object.keys(g.scene).slice(0, 20);
    }
    
    // Procura store/state
    if (g.store) out.store_keys = Object.keys(g.store).slice(0, 20);
    if (g.state) out.state_keys = Object.keys(g.state).slice(0, 20);
    if (g.config) out.config_keys = Object.keys(g.config).slice(0, 20);
    
    // Deep search for hp/life/health
    function deepFind(obj, depth, prefix) {
        if (depth > 3 || !obj || typeof obj !== 'object') return;
        for (var k in obj) {
            try {
                var kl = k.toLowerCase();
                if (kl === 'hp' || kl === 'life' || kl === 'health' || kl === 'maxhp' || 
                    kl === 'mp' || kl === 'mana' || kl === 'maxmp' || kl === 'level' ||
                    kl === 'player' || kl === 'character' || kl === 'stats' ||
                    kl === 'vitals' || kl === 'combat') {
                    var v = obj[k];
                    if (typeof v === 'number') {
                        out[prefix + k] = v;
                    } else if (v && typeof v === 'object') {
                        var sub = {};
                        for (var sk in v) {
                            if (typeof v[sk] === 'number') sub[sk] = v[sk];
                        }
                        if (Object.keys(sub).length > 0) {
                            out[prefix + k] = sub;
                        }
                    }
                }
            } catch(e) {}
        }
    }
    
    deepFind(g, 0, 'g.');
    
    // Procura em g.config
    if (g.config) {
        deepFind(g.config, 0, 'config.');
    }
    
    // Procura em cenarios
    if (g.scene && g.scene.scenes) {
        for (var name in g.scene.scenes) {
            var sc = g.scene.scenes[name];
            if (sc) {
                out['scene_' + name + '_keys'] = Object.keys(sc).slice(0, 30);
                deepFind(sc, 0, 'scene_' + name + '.');
            }
        }
    }
    
    return out;
}""")

with open('phaser_game_state.txt', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("DONE")
b.close()
pw.stop()
