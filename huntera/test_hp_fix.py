"""Quick test of fixed HP/MP parser."""
import sys, json, time
sys.path.insert(0, '.')
from engine_huntera import HunteraBot

bot = HunteraBot()
if bot.iniciar():
    for i in range(5):
        e = bot.rodar_ciclo()
        print(f"Ciclo {i+1}: HP={e['hp']}/{e['hp_max']} MP={e['mp']}/{e['mp_max']} CAP={e['capacity_oz']:.0f} loot={e.get('tem_loot')} dispatches={e['dispatches_feitos']}")
        time.sleep(8)
    bot.fechar()
else:
    print("Falha ao iniciar")
