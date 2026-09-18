# -*- coding: utf-8 -*-
# Teste de envio REAL (1 moeda, BTC) - verifica foto + texto Telegram
import sys, os
wdir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, wdir); sys.path.insert(0, os.path.join(wdir, "futuro"))

def carregar_credenciais():
    # le credentials.env se existir (para nao depender so de env)
    p = r"C:\Users\danie\.config\opencode\credentials.env"
    if os.path.exists(p):
        for linha in open(p, encoding="utf-8", errors="ignore"):
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import types
carregar_credenciais()
mod = types.ModuleType("mf")
mod.__file__ = os.path.join(wdir, "futuro", "monitor_futuro.py")
src = open(mod.__file__, encoding="utf-8").read().split("# ---------------- MONITOR")[0]
code = compile(src, mod.__file__, "exec")
exec(code, mod.__dict__)

O,H,L,C,T = mod.dados_4h("BTCUSDT", 300)
sigs = mod.buscar_sinais(O,H,L,C)
print("sinais:", len(sigs))
idx, entry, stop, side = sigs[-1]
lev, notional, dist = mod.calc_alavancagem(entry, stop)
alvo = entry - 3*abs(entry-stop) if side=="S" else entry + 3*abs(entry-stop)
print("sinal:", side, "entry=%.2f stop=%.2f alvo=%.2f lev=%.2fx" % (entry, stop, alvo, lev))

img = mod.gerar_imagem("BTCUSDT", side, entry, stop, alvo, O,H,L,C,T, idx)
print("imagem:", img, os.path.getsize(img), "bytes")

from telegram import enviar_foto, enviar_mensagem
texto = mod.formatar_sinal("BTCUSDT", side, entry, stop, alvo, lev, notional, 50.0, 1)
ok, msg = enviar_foto(img, caption=texto)
print("FOTO:", ok, msg)
if not ok:
    ok2, msg2 = enviar_mensagem(texto)
    print("FALLBACK TEXTO:", ok2, msg2)