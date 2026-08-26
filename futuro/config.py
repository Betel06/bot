import os

PARES = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
    "BNBUSDT", "LTCUSDT",
]

# Rotacao: pares analisados por rodada (cobre a lista inteira em ciclos).
# 10 pares / 3 por rodada / ciclo de 300s -> cada par analisado a cada ~17 min.
PARES_POR_RODADA = 3

INTERVALO = "5m"
INTERVALO_MONITOR = 300

ENTRADA_USD = 2.0

# Alavancagem simulada (paper trading): multiplica ganhos e perdas.
ALAVANCAGEM = float(os.environ.get("FUTURO_ALAVANCAGEM", "5"))

# Filtros de risco
RR_MINIMO = 2.0
TIMEOUT_POSICAO_SEGUNDOS = 2 * 60 * 60  # 2 horas

MERCADO = "futuros"
