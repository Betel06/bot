import os

# ============================================================================
# CONFIGURACAO - Bot Daytrade M15 (Breakout de range + volume)
# Projeto: BOT/m15/
# ----------------------------------------------------------------------------
# IMPORTANTE: estes parametros sao HIPO TESES a validar no backtest. Nada
# aqui deve ir para producao antes de passar no backtest.py com edge positivo.
# ============================================================================

# Ativos operados (fase papel / backtest)
# ETH excluido: backtest mostrou PF<1 (perdedor) para esta estrategia.
# XRP e o ativo-motor (edge estavel +9.17 nos 2 anos, RR 1:1.5).
# BTC e SOL sao positivos no total mas instaveis entre anos (marginais).
PARES = ["XRPUSDT", "BTCUSDT", "SOLUSDT"]

# Timeframe de operacao e de contexto (tendencia maior)
INTERVALO = "15m"        # grafico de entrada (M15)
HTF_INTERVALO = "1h"     # grafico de contexto (tendencia) -- vela de entrada 4x maior

# Intervalo do monitor (segundos entre rodadas ao vivo)
INTERVALO_MONITOR = int(os.environ.get("M15_INTERVALO_MONITOR", "300"))

# ------------------------- LOGICA BREAKOUT DE RANGE -------------------------
# Os parametros abaixo sao variaveis a serem exploradas no backtest.
# O modelo de sinais esta em estrategia.py

# Janela de consolidacao: olha as ultimas N velas M15 para definir a faixa.
RANGE_LENGTH = int(os.environ.get("M15_RANGE_LENGTH", "48"))   # 48 x 15min = 12h de range

# Multiplicador de volume: vela de rompimento deve ter volume >= media * X
VOL_MULTIPLIER = float(os.environ.get("M15_VOL_MULT", "1.5"))
VOL_WINDOW = 20  # janela da media movel de volume

# Confirmacao: rompimento exige fechamento FORA da faixa (nao so o wick).
REQUER_FECHAMENTO = True

# ------------------------- FILTROS DE QUALIDADE -------------------------
# Validados no backtest (2 anos, 3 ativos):
#   - corpo/pavio: corta falsos rompimentos (melhora PF em todos os ativos)
#   - MACD: filtro de direcao que combina bem com corpo/pavio (total +12.36
#     vs +7.07 da base). Sozinho nao ajuda.
#   - stop ATR: DESCARTADO (aumentou o risco sem compensar, reduziu o total).
FILTRO_CORPO = os.environ.get("M15_FILTRO_CORPO", "1") != "0"
MAX_WICK_RATIO = float(os.environ.get("M15_MAX_WICK", "0.4"))
FILTRO_MACD = os.environ.get("M15_FILTRO_MACD", "1") != "0"
STOP_ATR = os.environ.get("M15_STOP_ATR", "0") != "0"   # desligado (validado ruim)
ATR_MULT = 1.5
ATR_LEN = 14

# Operar apenas em certos dias da semana (0=Seg..6=Dom). None = todos.
# TESTADO E DESCARTADO: filtro Qui+Sex falhou walk-forward (BTC perdeu -2.85
# na 1a janela) -> era overfit no XRP. Nao usar.
DIAS_OPERACAO = None  # ex.: [3, 4] para Quinta e Sexta (NAO use - overfit)

# Gestao de risco (R = distancia entrada->stop)
# Validado no backtest (2 anos): RR 1:1.5 deu o MELHOR edge no XRP (+9.17,
# WR ~50%, estavel nos 2 anos) vs RR 1:2 (+8.33). RR alto (2.5/3) reduz WR
# p/ ~30% e destroi o edge. Menos ambicioso aqui = mais consistente.
RR = float(os.environ.get("M15_RR", "1.5"))

# ------------------------- BACKTEST -------------------------
# Custo realista (fees + slippage) aplicado por ida e volta, para nao
# superestimar o edge. Valor em % do preco.
COST_PCT = float(os.environ.get("M15_COST_PCT", "0.06"))   # 0.06% por lado

# Quantos anos de dados historicos baixar por ativo
ANOS_BACKTEST = int(os.environ.get("M15_ANOS", "2"))

# Risco por trade (% da banca), realista, para calculo de curvas de capital
RISCO_POR_TRADE = float(os.environ.get("M15_RISCO", "0.02"))
BANCO_INICIAL = float(os.environ.get("M15_BANCO", "10.0"))

# ------------------------- FILTRO DE TENDENCIA HTF -------------------------
# Se True, so aceita COMPRA quando a tendencia 1h for de alta, e VENDA quando
# for de baixa. A tendencia e medida pela posicao do preco vs media movel 1h.
FILTRO_HTF = os.environ.get("M15_FILTRO_HTF", "1") != "0"
HTF_EMA_PERIOD = 50  # EMA do timeframe 1h que define o "lado" do contexto
