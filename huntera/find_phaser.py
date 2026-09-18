"""Encontra o Phaser game real."""
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
    
    // Phaser.GAMES
    if (typeof Phaser !== 'undefined') {
        out.phaser_exists = true;
        out.phaser_version = Phaser.VERSION;
        if (Phaser.GAMES) {
            out.games_count = Phaser.GAMES.length;
            if (Phaser.GAMES.length > 0) {
                var g = Phaser.GAMES[0];
                out.game_type = g.constructor ? g.constructor.name : 'unknown';
                out.game_keys = Object.keys(g).slice(0, 50);
                
                // Procura scene
                if (g.scene) {
                    out.scene_keys = Object.keys(g.scene).slice(0, 30);
                    if (g.scene.scenes) {
                        for (var name in g.scene.scenes) {
                            var sc = g.scene.scenes[name];
                            if (sc) {
                                out['scene_' + name] = Object.keys(sc).slice(0, 40);
                            }
                        }
                    }
                }
            }
        }
    } else {
        out.phaser_exists = false;
    }
    
    // Procura em data- attributes do canvas
    var canvases = document.querySelectorAll('canvas');
    out.canvas_count = canvases.length;
    out.canvases = [];
    canvases.forEach(function(c) {
        out.canvases.push({
            w: c.width, h: c.height,
            id: c.id, cls: c.className,
        });
    });
    
    // Procura __phaser ou similar no window
    var deep = [];
    function scan(obj, path, depth) {
        if (depth > 2 || !obj) return;
        try {
            for (var k in obj) {
                if (depth === 0 && k.length > 3) {
                    try {
                        var v = obj[k];
                        if (v && typeof v === 'object' && v.scene) {
                            deep.push(path + '.' + k + ' (has scene)');
                        }
                        if (v && typeof v === 'object' && (v.hp !== undefined || v.life !== undefined)) {
                            deep.push(path + '.' + k + ' (has hp/life)');
                        }
                    } catch(e) {}
                }
            }
        } catch(e) {}
    }
    scan(window, 'window', 0);
    out.window_scene_holders = deep;
    
    // Procura Angular component com game state
    var appRoot = document.querySelector('app-root');
    if (appRoot && appRoot.__ngContext__) {
        out.ng_context_type = typeof appRoot.__ngContext__;
        out.ng_context_len = Array.isArray(appRoot.__ngContext__) ? appRoot.__ngContext__.length : 'not-array';
    }
    
    // Procura game-shell
    var shell = document.querySelector('app-game-shell');
    if (shell && shell.__ngContext__) {
        var ctx = shell.__ngContext__;
        out.shell_ng = true;
        if (Array.isArray(ctx)) {
            out.shell_ng_len = ctx.length;
            // Procura objetos com hp/life no contexto
            for (var i = 0; i < Math.min(ctx.length, 50); i++) {
                var item = ctx[i];
                if (item && typeof item === 'object') {
                    try {
                        if (item.hp !== undefined || item.life !== undefined) {
                            out['ng_item_' + i] = {hp: item.hp, life: item.life, level: item.level};
                        }
                        if (item.scene !== undefined && item.scene !== null) {
                            out['ng_item_' + i + '_scene'] = typeof item.scene;
                        }
                    } catch(e) {}
                }
            }
        }
    }
    
    return out;
}""")

with open('phaser_real.txt', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("DONE")
b.close()
pw.stop()
