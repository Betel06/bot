"""Testa acesso ao game state do Phaser."""
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
    
    // 1. Procura window.game
    out.window_game = !!window.game;
    out.window_game_type = typeof window.game;
    
    // 2. Procura window.__PHASER_GAME__
    out.phaser_game = !!window.__PHASER_GAME__;
    
    // 3. Procura em todas as propriedades do window
    var phaserKeys = [];
    for (var k in window) {
        try {
            if (k.toLowerCase().indexOf('game') >= 0 || k.toLowerCase().indexOf('phaser') >= 0) {
                phaserKeys.push(k + ':' + typeof window[k]);
            }
        } catch(e) {}
    }
    out.game_keys = phaserKeys;
    
    // 4. Procura game via gameRef ou angular
    var angularKeys = [];
    try {
        var ng = document.querySelector('[ng-version]') || document.querySelector('app-root');
        if (ng) angularKeys.push('ng-found');
    } catch(e) {}
    out.angular = angularKeys;
    
    // 5. Tenta acessar game scene via canvas
    var canvas = document.querySelector('canvas');
    if (canvas) {
        out.canvas_found = true;
        out.canvas_w = canvas.width;
        out.canvas_h = canvas.height;
        // Phaser guarda referencia no canvas
        var keys = [];
        for (var k in canvas) {
            if (k.indexOf('__') === 0 || k.indexOf('phaser') >= 0 || k.indexOf('game') >= 0) {
                keys.push(k);
            }
        }
        out.canvas_keys = keys;
    }
    
    // 6. Procura nos containers Angular/Phaser
    try {
        var gameShell = document.querySelector('app-game-shell');
        if (gameShell) {
            var ngKeys = [];
            for (var k in gameShell) {
                if (k.startsWith('__ng') || k.startsWith('_ng')) {
                    ngKeys.push(k);
                }
            }
            out.game_shell_ng = ngKeys;
        }
    } catch(e) {}
    
    // 7. Procura HP em spans com classe vazia (que sao do Phaser overlay)
    var hpSpans = document.querySelectorAll('div.hud-bar.hud-hp span, div.hud-bar.hud-mp span');
    out.hp_mp_spans = [];
    hpSpans.forEach(function(el) {
        out.hp_mp_spans.push({
            cls: el.className,
            text: el.textContent.trim(),
            style_width: el.style.width,
            computed_width: window.getComputedStyle(el).width,
            transform: window.getComputedStyle(el).transform,
        });
    });
    
    return out;
}""")

with open('phaser_test.txt', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("DONE")
b.close()
pw.stop()
