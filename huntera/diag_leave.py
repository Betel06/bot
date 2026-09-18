"""Testa de perto o clique em 'Sair da caçada' monitorando popups de confirmacao."""
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
    def snap(tag):
        d = bot.page.evaluate(r"""() => {
            const out={};
            const sel=[];
            document.querySelectorAll('button,[class*="hud-"]').forEach(el=>{
                const r=el.getBoundingClientRect(); if(r.width<2||r.height<2)return;
                const cls=(el.className||'').toString();
                if(/leave|sair|confirm|dialog|cancel|sim|nao/i.test(cls+(el.textContent||'')))
                    sel.push({cls:cls.substring(0,60), txt:(el.textContent||'').trim().replace(/\s+/g,' ').substring(0,30)});
            });
            out.leave_btns=sel;
            out.modais=[];
            document.querySelectorAll('.modal,.popup,[class*="modal"],[class*="dialog"],[class*="confirm"]').forEach(m=>{
                const r=m.getBoundingClientRect(); if(r.width<40||r.height<40)return;
                out.modais.push(m.textContent.trim().replace(/\s+/g,' ').substring(0,80));
            });
            return out;
        }""")
        print("[%s] modais=%s" % (tag, d.get('modais')))
        for b in d.get('leave_btns', []): print("    leave:", b)
    snap("estado_atual")
    print("em_cidade:", bot._em_cidade_agora())
finally:
    bot.fechar()
print("DONE")
