print("=" * 65)
print("  PROJECAO MENSAL - 5 PARES - R$100 POR POSICAO")
print("=" * 65)
print()
print("  DADOS DA ESTRATEGIA:")
print("  Timeframe: 5m")
print("  Stop Loss: 3%")
print("  Take Profit: 3%")
print("  Win Rate (teste real): 66.7%")
print("  Duracao media trade: 30-60 min")
print()

print("=" * 65)
print("  TABELA DE TRADES POR DIA")
print("=" * 65)
print()
print("  {:12s} | {:>6s} | {:>6s} | {:>6s} | {:>10s}".format(
    "Par", "Sinais", "Wins", "Losses", "Lucro/Dia"))
print("  " + "-" * 55)

pares = ["ATOMUSDT", "UNIUSDT", "ADAUSDT", "LINKUSDT", "XRPUSDT"]
total_sinais = 0
total_wins = 0
total_losses = 0

for par in pares:
    sinais = 2
    wins = int(sinais * 0.667)
    losses = sinais - wins
    lucro = (wins * 3) - (losses * 3)
    total_sinais += sinais
    total_wins += wins
    total_losses += losses
    print("  {:12s} | {:6d} | {:6d} | {:6d} | R${:+5.2f}".format(
        par, sinais, wins, losses, lucro))

print("  " + "-" * 55)
lucro_dia = (total_wins * 3) - (total_losses * 3)
print("  {:12s} | {:6d} | {:6d} | {:6d} | R${:+5.2f}".format(
    "TOTAL", total_sinais, total_wins, total_losses, lucro_dia))

print()
print("=" * 65)
print("  DETALHAMENTO POR OPERACAO")
print("=" * 65)
print()
print("  Capital total: R$500.00")
print("  Por posicao:   R$100.00")
print()
print("  Se WIN (+3%):   R$100 x 3%  = +R$3.00")
print("  Se LOSS (-3%):  R$100 x 3%  = -R$3.00")

print()
print("=" * 65)
print("  CENARIOS DO MES (30 DIAS)")
print("=" * 65)
print()
print("  {:16s} | {:>5s} | {:>5s} | {:>8s} | {:>8s} | {:>8s}".format(
    "Cenario", "W%", "L%", "Wins", "Losses", "Lucro"))
print("  " + "-" * 65)

cenarios = [
    ("Muito ruim", 35, 65),
    ("Ruim", 45, 55),
    ("Neutro", 55, 45),
    ("Bom (hoje)", 66, 34),
    ("Muito bom", 75, 25),
    ("Excelente", 80, 20),
]

for nome, wr, lr in cenarios:
    wins_mes = int(wr * 0.1)
    losses_mes = int(lr * 0.1)
    ganho = wins_mes * 3
    perda = losses_mes * 3
    lucro = ganho - perda
    print("  {:16s} | {:4d}% | {:4d}% | {:6d} | {:6d} | R${:+7.2f}".format(
        nome, wr, lr, wins_mes, losses_mes, lucro))

print()
print("  * Estimando ~10 trades por dia (2 sinais x 5 pares)")
print()
print("=" * 65)
print("  PROJECAO REALISTA")
print("=" * 65)
print()
print("  Sinais por dia: ~10 (2 por par)")
print("  Duracao media: 30-60 min")
print("  Win rate: 66%")
print()
print("  {:20s} | {:>8s} | {:>8s} | {:>10s}".format(
    "Periodo", "Wins", "Losses", "Lucro"))
print("  " + "-" * 55)

periodos = [
    ("1 dia", 7, 3),
    ("1 semana", 47, 23),
    ("2 semanas", 93, 47),
    ("1 mes", 200, 100),
]

for nome, w, l in periodos:
    ganho = w * 3
    perda = l * 3
    lucro = ganho - perda
    print("  {:20s} | {:8d} | {:8d} | R${:+8.2f}".format(
        nome, w, l, lucro))

print()
print("=" * 65)
print("  RESUMO")
print("=" * 65)
print()
print("  Com R$500 (R$100 x 5 pares):")
print()
print("  1 dia:    R$+12")
print("  1 semana: R$+72")
print("  1 mes:    R$+300 (+60%)")
print()
print("  Se win rate cair pra 55%:")
print("  1 mes:    R$+30 (+6%)")
print()
print("  Se win rate cair pra 45%:")
print("  1 mes:    R$-60 (-12%)")
print()
print("=" * 65)
