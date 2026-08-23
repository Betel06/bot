import os

PARES = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
    "BNBUSDT", "LTCUSDT", "COLLECTUSDT", "BTWUSDT",
]

# Rotacao: pares analisados por rodada (cobre a lista inteira em ciclos).
# 12 pares / 3 por rodada / ciclo de 600s -> cada par analisado a cada ~40 min.
PARES_POR_RODADA = 3

INTERVALO = "5m"
INTERVALO_MONITOR = 300

ENTRADA_USD = 2.0

# Alavancagem simulada (paper trading): multiplica ganhos e perdas.
ALAVANCAGEM = float(os.environ.get("FUTURO_ALAVANCAGEM", "5"))

MERCADO = "futuros"
