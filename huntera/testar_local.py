import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine_huntera import HunteraBot
import time, json, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

bot = HunteraBot()
if bot.iniciar():
    print("Bot iniciado! Rodando 20 ciclos...")
    for i in range(20):
        estado = bot.rodar_ciclo()
        print(json.dumps({k: v for k, v in estado.items() if k != 'ultimo_update'}, ensure_ascii=False))
        time.sleep(8)
else:
    print("Falha ao iniciar bot.")
bot.fechar()
