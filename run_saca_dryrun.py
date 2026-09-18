# -*- coding: utf-8 -*-
# Teste offline (dry-run): fetch + sinais + alavancagem + resultado
import sys, os
wdir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, wdir)
sys.path.insert(0, os.path.join(wdir, "futuro"))

import importlib.util
spec = importlib.util.spec_from_file_location("mf", os.path.join(wdir, "futuro", "monitor_futuro.py"))

import types
mod = types.ModuleType("mf")
# injeta __file__ antes do exec
mod.__file__ = os.path.join(wdir, "futuro", "monitor_futuro.py")
import io
src = open(mod.__file__, encoding="utf-8").read()
src = src.split("# ---------------- MONITOR")[0]
src = src.replace('from telegram import enviar_mensagem, enviar_foto', '')

from datetime import datetime, timezone
import numpy as np

code = compile(src, mod.__file__, "exec")
exec(code, mod.__dict__)

MOEDAS = mod.MOEDAS
print("="*110)
print("%-9s %-5s %-12s %-12s %-12s %-8s %-8s %-9s %-7s %-8s %-8s" % ("MOEDA","lado","ENTRADA","STOP","ALVO","dist%","lev x","notional","RESULT","bruto","liq"))
tot = 0
for sym in MOEDAS:
    O,H,L,C,T = mod.dados_4h(sym, 300)
    sigs = mod.buscar_sinais(O,H,L,C)
    if not sigs:
        print("%-9s sem sinal (300 velas)" % sym); continue
    idx, entry, stop, side, pavio = sigs[-1]
    lev, notional, dist = mod.calc_alavancagem(entry, stop)
    alvo = entry - mod.ALVO_R*abs(entry-stop) if side=="S" else entry + mod.ALVO_R*abs(entry-stop)
    res, saida, jfim = mod.computar_resultado(entry, stop, side, idx, O,H,L,C)
    pl = mod.ALVO_R if res=="WIN" else (-1.0 if res=="LOSS" else ( -1* (saida-entry)/abs(entry-stop) if side=="S" else (saida-entry)/abs(entry-stop)))
    nvp = max(0, jfim - idx)
    c = mod.calc_custos(entry, saida, side, notional, nvp)
    liq = pl - c["total"]
    tot += liq
    print("%-9s %-5s %-12.4f %-12.4f %-12.4f %-7.2f %-8.2f %-9.2f %-7s %-+8.2f %-+8.2f  (fees %.4f fund %.4f)" % (sym, side, entry, stop, alvo, dist*100, lev, notional, res, pl, liq, c["fee_entrada"]+c["fee_saida"], c["funding"]))
print("="*110)
print("P/L LIQUIDO das ultimas entradas (com custos): %+.2f" % tot)
print("DRY-RUN OK - nenhuma mensagem enviada.")