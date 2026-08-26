"""
Gerenciamento de Risco - Position Sizing, Kelly Criterion, Metodos de Saida

Baseado nos conceitos do video MASTER AI Trading:
- Position sizing baseado em risco % por trade
- Kelly Criterion para sizing otimo
- Trailing stop e take profit escalonado
- Max drawdown protection
"""
import math


def calcular_tamanho_posicao(
    capital,
    risco_pct,
    entrada,
    stop,
    alavancagem=1,
    max_capital_pct=0.95,
):
    """
    Calcula tamanho da posicao baseado em risco fixo %.

    Args:
        capital: Saldo total da conta
        risco_pct: Risco por trade (0.02 = 2%)
        entrada: Preco de entrada
        stop: Preco do stop loss
        alavancagem: Alavancagem (1 = spot)
        max_capital_pct: Max % do capital em uma posicao

    Returns:
        dict com tamanho, valor_risco, peso_carteira, etc.
    """
    if capital <= 0 or entrada <= 0:
        return None

    stop_distancia = abs(entrada - stop) / entrada
    if stop_distancia <= 0:
        return None

    valor_risco = capital * risco_pct
    tamanho_usd = valor_risco / stop_distancia
    max_usd = capital * max_capital_pct * alavancagem

    if tamanho_usd > max_usd:
        tamanho_usd = max_usd

    peso = tamanho_usd / (capital * alavancagem)

    return {
        "tamanho_usd": round(tamanho_usd, 2),
        "valor_risco": round(valor_risco, 2),
        "stop_distancia_pct": round(stop_distancia * 100, 2),
        "peso_carteira": round(peso * 100, 1),
        "risco_restante_pct": round((1 - peso) * 100, 1),
    }


def kelly_criterion(win_rate, avg_win, avg_loss):
    """
    Calcula fracao optima de Kelly para sizing.

    Kelly % = (bp - q) / b
    b = media_ganhos / media_perdas (odds)
    p = win_rate
    q = 1 - p

    Returns:
        dict com kelly_pct, kelly_frac (fracao conservadora)
    """
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return {"kelly_pct": 0, "kelly_frac": 0, "fracao": "N/A"}

    b = avg_win / abs(avg_loss)
    p = win_rate
    q = 1 - p

    kelly = (b * p - q) / b
    kelly = max(kelly, 0)

    kelly_frac = kelly * 0.25

    if kelly < 0.01:
        fracao = "NAO OPERAR"
    elif kelly < 0.05:
        fracao = "MINIMA (1/4 Kelly)"
    elif kelly < 0.15:
        fracao = "CONSERVADORA (1/4 Kelly)"
    elif kelly < 0.25:
        fracao = "MODERADA (1/4 Kelly)"
    else:
        fracao = "AGRESSIVA (1/4 Kelly)"

    return {
        "kelly_pct": round(kelly * 100, 1),
        "kelly_frac": round(kelly_frac * 100, 1),
        "odds": round(b, 2),
        "fracao": fracao,
    }


def calcular_rr(entrada, stop, alvo):
    """Calcula Risk:Reward ratio."""
    risco = abs(entrada - stop)
    recompensa = abs(alvo - entrada)
    if risco == 0:
        return 0
    return round(recompensa / risco, 2)


def trailing_stop(entrada, preco_atual, direcao, trailing_pct=0.03):
    """
    Calcula trailing stop baseado no preco atual.

    Args:
        entrada: Preco de entrada
        preco_atual: Preco atual do ativo
        direcao: 'COMPRA' ou 'VENDA'
        trailing_pct: % de trailing stop

    Returns:
        preco_stop do trailing
    """
    if direcao == "COMPRA":
        lucro_pct = (preco_atual - entrada) / entrada
        if lucro_pct > trailing_pct:
            return preco_atual * (1 - trailing_pct)
    else:
        lucro_pct = (entrada - preco_atual) / entrada
        if lucro_pct > trailing_pct:
            return preco_atual * (1 + trailing_pct)

    return None


def take_profit_escalonado(entrada, direcao, alvos_pct=None):
    """
    Gera niveis de take profit escalonados.

    Args:
        entrada: Preco de entrada
        direcao: 'COMPRA' ou 'VENDA'
        alvos_pct: Lista de [%lucro, %do_total_a_sair]

    Returns:
        Lista de dict com niveis
    """
    if alvos_pct is None:
        alvos_pct = [
            (0.02, 0.33),
            (0.05, 0.33),
            (0.10, 0.34),
        ]

    niveis = []
    for pct_lucro, pct_saida in alvos_pct:
        if direcao == "COMPRA":
            preco_alvo = entrada * (1 + pct_lucro)
        else:
            preco_alvo = entrada * (1 - pct_lucro)

        niveis.append({
            "nivel": len(niveis) + 1,
            "preco": round(preco_alvo, 6),
            "lucro_pct": round(pct_lucro * 100, 1),
            "saida_pct": round(pct_saida * 100, 0),
        })

    return niveis


def max_drawdown_protection(saldo_inicial, saldo_atual, max_dd_pct=0.20):
    """
    Verifica se atingiu o drawdown maximo permitido.

    Returns:
        dict com status, dd_pct, deve_parar
    """
    if saldo_inicial <= 0:
        return {"dd_pct": 0, "deve_parar": False, "status": "OK"}

    dd = (saldo_inicial - saldo_atual) / saldo_inicial
    deve_parar = dd >= max_dd_pct

    if dd < 0.05:
        status = "OK"
    elif dd < 0.10:
        status = "ATENCAO"
    elif dd < 0.15:
        status = "PERIGO"
    elif dd < max_dd_pct:
        status = "CRITICO"
    else:
        status = "BLOQUEADO"

    return {
        "dd_pct": round(dd * 100, 1),
        "deve_parar": deve_parar,
        "status": status,
        "saldo_atual": round(saldo_atual, 2),
        "saldo_inicial": round(saldo_inicial, 2),
    }


def risco_diario(posicoes_hoje, capital, risco_max_diario_pct=0.05):
    """
    Controle de risco diario - quantos trades e quanto ja arriscou.

    Args:
        posicoes_hoje: Lista de trades executados hoje
        capital: Capital atual
        risco_max_diario_pct: Max % do capital arriscado por dia

    Returns:
        dict com trades_hoje, risco_usado, pode_operar
    """
    risco_total = sum(
        abs(t.get("entrada", 0) - t.get("stop", 0)) / t.get("entrada", 1)
        for t in posicoes_hoje
        if t.get("entrada") and t.get("stop")
    )

    risco_max = capital * risco_max_diario_pct
    risco_usado_usd = sum(
        t.get("risco_valor", 0) for t in posicoes_hoje
    )

    pode_operar = risco_usado_usd < risco_max and len(posicoes_hoje) < 5

    return {
        "trades_hoje": len(posicoes_hoje),
        "risco_usado_usd": round(risco_usado_usd, 2),
        "risco_max_usd": round(risco_max, 2),
        "pode_operar": pode_operar,
        "risco_restante_pct": round(
            max(0, (risco_max - risco_usado_usd) / risco_max * 100), 1
        ),
    }


def avaliar_trade(preco, stop, alvo, capital, risco_pct=0.02, alavancagem=1):
    """
    Avaliacao completa de um trade antes de executar.

    Returns:
        dict com todas as metricas
    """
    rr = calcular_rr(preco, stop, alvo)
    sizing = calcular_tamanho_posicao(
        capital, risco_pct, preco, stop, alavancagem
    )

    if not sizing:
        return {"valido": False, "motivo": "Sizing invalido"}

    risco_valor = abs(preco - stop) / preco * sizing["tamanho_usd"] * alavancagem
    recompensa_valor = abs(alvo - preco) / preco * sizing["tamanho_usd"] * alavancagem

    return {
        "valido": True,
        "rr": rr,
        "rr_aceitavel": rr >= 2.0,
        "tamanho": sizing,
        "risco_valor": round(risco_valor, 2),
        "recompensa_valor": round(recompensa_valor, 2),
        "risco_pesado": risco_valor > capital * 0.10,
    }
