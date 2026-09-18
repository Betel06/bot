"""Inspeciona estado atual: ha modal de venda aberto? botao venda rapida visivel?"""
import sys, os, time, io, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
from engine_huntera import HunteraBot

bot = HunteraBot()
if not bot.iniciar(visivel=True):
    sys.exit(1)
try:
    time.sleep(4)
    bot._acao_fechar_popups()
    time.sleep(2)
    d = bot.page.evaluate(r"""() => {
        const out={};
        const qs=document.querySelector('button.hud-city-action.hud-quick-sell');
        out.qs_visivel_bbox = qs? (()=>{const r=qs.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)};})() : null;
        // Modais/popups visiveis
        out.modais = Array.from(document.querySelectorAll('.modal,.popup,[class*="modal"],[class*="dialog"],[class*="confirm"],[class*="modal-backdrop"]'))
            .filter(e=>{const r=e.getBoundingClientRect();return r.width>50&&r.height>50;})
            .map(m=>m.textContent.trim().replace(/\s+/g,' ').substring(0,120));
        // botoes visiveis na tela
        out.btns = Array.from(document.querySelectorAll('button,[role=button]'))
            .filter(e=>{const r=e.getBoundingClientRect();return r.width>2&&r.height>2;})
            .map(b=>(b.textContent||'').trim().replace(/\s+/g,' ').substring(0,22))
            .filter(t=>t);
        return out;
    }""")
    print("QUICKSELL bbox:", d.get('qs_visivel_bbox'))
    print("MODAIS:", d.get('modais'))
    print("BOTOES:", d.get('btns'))
finally:
    bot.fechar()
print("DONE")
