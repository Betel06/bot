"""
Cerebro de IA para decisoes de trading (SMC).
Recebe dados multi-timeframe da Binance (spot ou futuros), aplica o framework
SMC via LLM (Gemini) e retorna um sinal estruturado com raciocinio.

Env vars:
    AI_ENABLED=1          -> ativa o cerebro
    GEMINI_API_KEY=...    -> chave da API (aistudio.google.com)
    AI_MODEL=...          -> default: gemini-3.5-flash
"""

import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))  # horario de Brasilia fixo (independe do servidor)

import requests

from core.dados import buscar_historico
from core.indicadores import (
    calcular_rsi, calcular_ema, calcular_adx, calcular_supertrend, calcular_atr,
    detectar_bos
)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Cadeia de modelos: cota diaria e POR MODELO; se um esgotar, usa o proximo.
# Lista validada contra a API em 22/08 (testes reais de generateContent):
# gemini-2.5-flash/-lite retornam 404 nessa key; nao usar.
MODELOS = [m.strip() for m in os.environ.get(
    "AI_MODELS",
    "gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash,gemini-3.5-flash-lite,"
    "gemini-3.1-flash-lite,gemini-flash-latest,gemini-flash-lite-latest"
).split(",") if m.strip()]
MODELO = os.environ.get("AI_MODEL", MODELOS[0])
_MODELO_ATIVO = None

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

# Timeframes por mercado: futuros = day trade rapido; spot = swing multi-TF;
# b3 = day trade em mini dolar (dados da B3 via TradingView)
TFS_POR_MERCADO = {
    "spot": (("4h", 40), ("1h", 50), ("15m", 60)),
    "futuros": (("1h", 40), ("15m", 50), ("5m", 60)),
    "b3": (("60m", 40), ("15m", 50), ("5m", 60)),
}

PROMPT_FUTUROS = """
CONTEXTO DA OPERACAO: voce opera FUTUROS de cripto em DAY TRADE (ciclos rapidos, posicoes de minutos a poucas horas).
- Long e Short sao igualmente naturais: opere os dois lados conforme a estrutura.
- Velocidade importa: priorize o que acontece no 15m/5m, usando o 1h so como direcao geral.
- Disciplina de risco e inegociavel: sem alavancagem alta sem confluencia; se o R:R minimo nao aparecer, NADA.

FILTRO DE TENDENCIA (OBRIGATORIO):
- Voce recebe indicadores pre-calculados (EMA, RSI, ADX, SuperTrend). USE-OS.
- Se Tendencia EMA = "BAIXA" ou "BAIXA FORTE": so permita VENDA (SHORT). COMPRA e PROIBIDO.
- Se Tendencia EMA = "ALTA" ou "ALTA FORTE": so permita COMPRA (LONG). VENDA e PROIBIDO.
- Se Tendencia EMA = "LATERAL": os dois lados sao permitidos, mas so com confluencia forte.
- Se SuperTrend = "VENDA": nao abra COMPRA. Se SuperTrend = "COMPRA": nao abra VENDA.
- Se ADX < 20: tendencia fraca, considere NADA (mercado lateral sem direcao clara).

BOS - BREAK OF STRUCTURE (OBRIGATORIO PARA ENTRADA):
- NUNCA entre sem um BOS confirmado na direcao do trade.
- COMPRA so se BOS = "ALTA" (preco quebrou swing high para cima = continuacao de alta).
- VENDA so se BOS = "BAIXA" (preco quebrou swing low para baixo = continuacao de baixa).
- Se NAO ha BOS claro, NADA e a resposta. Entrar sem BOS e gambiarra.
- O campo "bos" no JSON DEVE conter: "ALTA", "BAIXA", ou "NENHUM".

R:R MINIMO = 2.0. Abaixo disso, NADA.
""".strip()

PROMPT_B3 = """
CONTEXTO DA OPERACAO: voce opera FUTUROS da B3 (Brasil) em DAY TRADE no MINI DOLAR WDO
(contrato continuo WDO1!, precos em PONTOS; tick 0,5 ponto = R$5 por contrato; 1 ponto = R$10).
- Long e Short sao igualmente naturais: opere os dois lados conforme a estrutura.
- Sessao 09h00-18h25 BRT. Voce so e acionado dentro das killzones:
  ABERTURA BRASIL (09h00-10h30), ABERTURA NY (10h30-12h30) e TARDE (15h00-17h00).
- Referencias de liquidez proprias do WDO: maxima/minima do dia anterior, gap de abertura,
  topo/fundo da madrugada (overnight range) e PTAX. Sweep desses niveis e evento chave.
- O WDO reage FORTE a macro (COPOM, Focus, payroll, Fed, dados BR): perto de evento,
  leitura tecnica pura nao vale — a resposta correta e NADA.
- Velocidade importa: priorize o 15m/5m, usando o 60m so como direcao geral.
- Disciplina inegociavel: sem confluencia e R:R minimo, NADA. Stop onde a tese morre
  (alem do sweep/OB), alvo na liquidez oposta.
""".strip()

# ---------------------------------------------------------------------------
# CONHECIMENTO SMC condensado (fonte: docs/smc_knowledge.md - Azvdou/ICT)
# ---------------------------------------------------------------------------

PROMPT_SISTEMA = """Voce e um trader profissional de day trade especialista em Smart Money Concepts (SMC/ICT).
Analise os dados de mercado fornecidos e decida se ha uma operacao de ALTA qualidade agora.

SUA AUTONOMIA:
- Voce e a AUTORIDADE FINAL da decisao. Nenhum filtro externo vai revisar ou vetar o seu sinal.
- Use TUDO o que voce sabe: estrutura, liquidez, sweeps, OB/FVG, premium/discount, PO3,
  killzones, volatilidade, contexto de ciclo, comportamento de preco — sua experiencia completa.
- Voce define entrada, stop e alvo como um trader real: stop onde a tese morre, alvo na liquidez oposta.
- Se a operacao nao fizer sentido para voce, NADA e a resposta certa. Se fizer, execute com conviccao.
- Porem lembre-se: cada decisao fica registrada em auditoria. Liberdade total exige disciplina total.

FRAMEWORK DE ANALISE (referencia, nao amarra):
1. ESTRUTURA: identifique HH/HL (alta) ou LH/LL (baixa) em cada timeframe. Ultimo evento foi BOS (continuacao) ou CHoCH/MSS (reversao)?
2. LIQUIDEZ: onde estao os stops? Equal highs/lows, topos/fundos recentes (BSL acima, SSL abaixo). Houve SWEEP recente?
3. ZONAS: existe OB valido ou FVG nao mitigado perto do preco?
4. PREMIUM/DISCOUNT: preco esta na metade inferior (discount) ou superior (premium) do range atual?
5. CONFLUENCIA: os melhores trades tem 3+ fatores alinhados.
6. GESTAO: risco/retorno faz parte das suas habilidades — aplique-o como achar correto.

REGRAS CRITICAS:
- Estrutura do timeframe MAIOR manda na direcao geral.
- NUNCA invente niveis: use precos reais dos candles fornecidos.

RESPONDA APENAS COM JSON VALIDO neste formato exato:
{
  "sinal": "COMPRA" | "VENDA" | "NADA",
  "bos": "ALTA" | "BAIXA" | "NENHUM",
  "confianca": 0-100,
  "preco": <preco atual>,
  "stop": <nivel do stop>,
  "alvo": <nivel do alvo>,
  "estrutura": "<resumo da estrutura multi-TF>",
  "liquidez": "<onde esta a liquidez / houve sweep?>",
  "zona": "<OB/FVG relevante ou 'nenhuma'>",
  "motivo": "<raciocinio completo em 2-4 frases>"
}
Se sinal for NADA, stop/alvo/preco podem ser o preco atual e motivo explica por que ficar fora."""


def _fmt_candles(df, n):
    d = df.tail(n)
    linhas = []
    for _, r in d.iterrows():
        linhas.append("O:{:.6g} H:{:.6g} L:{:.6g} C:{:.6g}".format(
            float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    return "\n".join(linhas)


def _calcular_indicadores(df):
    """Calcula indicadores tecnicos e retorna string formatada pro prompt."""
    if df is None or len(df) < 30:
        return ""

    close = df["close"]
    high = df["high"]
    low = df["low"]

    ema9 = calcular_ema(close, 9).iloc[-1]
    ema21 = calcular_ema(close, 21).iloc[-1]
    ema50 = calcular_ema(close, 50).iloc[-1] if len(df) >= 50 else None
    rsi = calcular_rsi(close, 14).iloc[-1]
    adx, plus_di, minus_di = calcular_adx(high, low, close, 14)
    adx_val = adx.iloc[-1]
    plus_di_val = plus_di.iloc[-1]
    minus_di_val = minus_di.iloc[-1]
    st, st_dir = calcular_supertrend(high, low, close, 10, 3)
    st_direcao = "COMPRA" if st_dir.iloc[-1] == 1 else "VENDA"
    atr = calcular_atr(high, low, close, 14).iloc[-1]

    if ema9 > ema21:
        tendencia = "ALTA"
    elif ema9 < ema21:
        tendencia = "BAIXA"
    else:
        tendencia = "LATERAL"

    if ema50 is not None:
        if ema9 > ema21 > ema50:
            tendencia = "ALTA FORTE"
        elif ema9 < ema21 < ema50:
            tendencia = "BAIXA FORTE"

    partes = [
        "--- INDICADORES PRE-CALCULADOS (1h) ---",
        "EMA9: {:.6g} | EMA21: {:.6g} | EMA50: {}".format(
            ema9, ema21, "{:.6g}".format(ema50) if ema50 else "N/A"),
        "Tendencia EMA: {} (EMA9 vs EMA21 vs EMA50)".format(tendencia),
        "RSI(14): {:.1f}".format(rsi),
        "ADX(14): {:.1f} | +DI: {:.1f} | -DI: {:.1f} (forca da tendencia)".format(
            adx_val, plus_di_val, minus_di_val),
        "SuperTrend(10,3): {} (direcao atual)".format(st_direcao),
        "ATR(14): {:.6g} (volatilidade)".format(atr),
        _calcular_bos(df),
        "--- FIM INDICADORES ---",
    ]
    return "\n".join(partes)


def _calcular_bos(df):
    """Detecta BOS nos candles e retorna string formatada pro prompt."""
    if df is None or len(df) < 15:
        return "BOS: dados insuficientes"

    high = df["high"]
    low = df["low"]
    close = df["close"]

    bos, preco_swing = detectar_bos(high, low, close)

    if bos == "BOS_ALTA":
        return "BOS DETECTADO: ALTA (quebrou swing high em {:.6g})".format(preco_swing)
    elif bos == "BOS_BAIXA":
        return "BOS DETECTADO: BAIXA (quebrou swing low em {:.6g})".format(preco_swing)
    else:
        return "BOS: NENHUM DETECTADO (sem quebra de estrutura)"


def _buscar_candles(par, intervalo, n, mercado):
    if mercado == "b3":
        from core.dados_b3 import buscar_historico_b3
        return buscar_historico_b3(par, intervalo, n)
    return buscar_historico(par, intervalo, n, mercado=mercado)


def coletar_contexto(par, mercado="spot"):
    """Monta o contexto multi-timeframe compacto de um par."""
    partes = ["PAR: {} ({})".format(par, mercado.upper())]
    tfs = TFS_POR_MERCADO.get(mercado, TFS_POR_MERCADO["spot"])

    for tf, n in tfs:
        try:
            df = _buscar_candles(par, tf, n, mercado)
            if df is None or len(df) == 0:
                continue
            partes.append("\n=== CANDLES {} (mais recentes por ultimo) ===".format(tf))
            partes.append(_fmt_candles(df, n))

            if tf == "1h":
                indicadores = _calcular_indicadores(df)
                if indicadores:
                    partes.append("\n" + indicadores)
        except Exception as e:
            partes.append("\n=== CANDLES {}: erro ({}) ===".format(tf, e))

    return "\n".join(partes)


def _validar(decisao, preco_ref):
    """
    Sanidade estrutural minima (nao veto de estrategia — a IA e a autoridade).
    Retorna (decisao_ok, erro_ou_none).
    """
    if not isinstance(decisao, dict):
        return None, "resposta nao e um objeto"
    sinal = str(decisao.get("sinal", "")).upper().strip()
    if sinal not in ("COMPRA", "VENDA", "NADA"):
        return None, "sinal invalido: {}".format(sinal)

    try:
        preco = float(decisao.get("preco") or preco_ref)
        stop = float(decisao.get("stop") or 0)
        alvo = float(decisao.get("alvo") or 0)
    except (TypeError, ValueError):
        return None, "numeros invalidos"

    if sinal == "NADA":
        decisao["preco"] = preco
        return decisao, None

    # Validacao BOS: obrigatorio para entradas
    bos = str(decisao.get("bos", "NENHUM")).upper().strip()
    if sinal == "COMPRA" and bos != "ALTA":
        return None, "COMPRA sem BOS ALTA (bos={})".format(bos)
    if sinal == "VENDA" and bos != "BAIXA":
        return None, "VENDA sem BOS BAIXA (bos={})".format(bos)

    if preco <= 0:
        return None, "preco <= 0"

    # Sanidade direcional apenas: os niveis tem que fazer sentido geometricamente.
    if sinal == "COMPRA":
        if not (0 < stop < preco < alvo):
            return None, "niveis inconsistentes p/ COMPRA (precisa stop<preco<alvo)"
    else:
        if not (0 < alvo < preco < stop):
            return None, "niveis inconsistentes p/ VENDA (precisa alvo<preco<stop)"

    risco = abs(preco - stop)
    retorno = abs(alvo - preco)
    rr = retorno / risco if risco > 0 else 0.0
    decisao["rr"] = round(rr, 2)

    decisao["preco"] = preco
    decisao["stop"] = stop
    decisao["alvo"] = alvo
    return decisao, None


def _chamar_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, "GEMINI_API_KEY nao configurada"

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 8192,
        },
    }

    global _MODELO_ATIVO
    ordem = list(MODELOS)
    if _MODELO_ATIVO and _MODELO_ATIVO in ordem:
        ordem.remove(_MODELO_ATIVO)
        ordem.insert(0, _MODELO_ATIVO)

    ultimo_erro = "nenhum modelo tentado"
    for modelo in ordem:
        url = GEMINI_URL.format(model=modelo)
        for tentativa in range(2):
            try:
                resp = requests.post(url, json=body, timeout=60, headers={"x-goog-api-key": key})
            except Exception as e:
                ultimo_erro = "{}: {}".format(modelo, e)
                break

            if resp.status_code == 200:
                _MODELO_ATIVO = modelo
                data = resp.json()
                try:
                    texto = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    return None, "resposta sem texto: {}".format(json.dumps(data)[:300])
                return texto, None

            if resp.status_code == 429:
                delay = 20
                try:
                    rd = resp.json().get("error", {}).get("details", [])
                    for d in rd:
                        if d.get("@type", "").endswith("RetryInfo"):
                            delay = min(int(float(d.get("retryDelay", "20s").rstrip("s"))) + 2, 60)
                except Exception:
                    pass
                logging.warning("[IA] {} 429 (tentativa {}), aguardando {}s".format(modelo, tentativa + 1, delay))
                time.sleep(delay)
                continue

            ultimo_erro = "{}: HTTP {}: {}".format(modelo, resp.status_code, resp.text[:200])
            break

    return None, ultimo_erro


LOG_IA = os.path.join(LOG_DIR, "ai_decisions.jsonl")


def _arquivo_log(mercado):
    if mercado == "futuros":
        return os.path.join(LOG_DIR, "ai_decisions_futuro.jsonl")
    if mercado == "b3":
        return os.path.join(LOG_DIR, "ai_decisions_b3.jsonl")
    return LOG_IA


def _registrar(par, resultado_bruto, final, erro, mercado="spot"):
    try:
        caminho = _arquivo_log(mercado)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        registro = {
            "data": datetime.now(BRT).strftime("%d/%m %H:%M:%S"),
            "mercado": mercado,
            "par": par,
            "erro": erro,
            "decisao_final": final,
            "resposta_bruta": (resultado_bruto or "")[:2000],
        }
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception:
        pass


def analisar_com_ia(par, mercado="spot", estudo=False):
    """
    Retorna dict no formato de sinal do monitor:
    {"sinal": "COMPRA"/"VENDA", "preco", "stop", "alvo", "rsi", "tendencia", "motivo"}
    ou None se nao ha sinal / houve erro.
    estudo=True: registra a decisao para auditoria mas NUNCA retorna sinal
    (usado pelo STUDY_MODE fora da sessao).
    """
    try:
        contexto = coletar_contexto(par, mercado)
        prompt = PROMPT_SISTEMA
        if mercado in ("futuros", "futuro"):
            prompt += "\n" + PROMPT_FUTUROS
        elif mercado == "b3":
            prompt += "\n" + PROMPT_B3
            try:
                from b3.config import janela_atual, em_blackout
                prompt += "\nJANELA ATUAL: {}".format(
                    em_blackout() and "BLACKOUT MACRO (proibido operar)"
                    or janela_atual() or "FORA DE KILLZONE (estudo)")
            except Exception:
                pass
        prompt += "\n\nDADOS DE MERCADO:\n" + contexto
        bruto, erro_api = _chamar_gemini(prompt)

        if erro_api:
            logging.error("[IA] {} erro api: {}".format(par, erro_api))
            _registrar(par, None, None, erro_api, mercado)
            return None

        try:
            decisao = json.loads(bruto)
        except json.JSONDecodeError:
            logging.error("[IA] {} json invalido".format(par))
            _registrar(par, bruto, None, "json invalido", mercado)
            return None

        preco_ref = 0.0
        try:
            df = _buscar_candles(par, "1m", 2, mercado)
            preco_ref = float(df["close"].iloc[-1])
        except Exception:
            pass

        final, erro_val = _validar(decisao, preco_ref)
        if erro_val:
            logging.info("[IA] {} descartado: {}".format(par, erro_val))
            _registrar(par, bruto, None, erro_val, mercado)
            return None

        _registrar(par, bruto, final, None, mercado)

        if estudo or final["sinal"] == "NADA":
            if estudo and final["sinal"] != "NADA":
                logging.info("[ESTUDO] {} sinal {} ignorado (fora de sessao)".format(
                    par, final["sinal"]))
            return None

        rr = float(final.get("rr") or 0)
        if rr < 2.0:
            logging.warning("[IA] {} REJEITADO R:R {} < 2.0 | {}".format(
                par, rr, str(final.get("motivo"))[:100]))
            _registrar(par, bruto, final, "R:R {} < 2.0".format(rr), mercado)
            return None

        logging.info("[IA] SINAL {} {} conf={} rr={} bos={} | {}".format(
            final["sinal"], par, final.get("confianca"), final.get("rr"),
            final.get("bos", "?"), str(final.get("motivo"))[:120]))

        return {
            "par": par,
            "sinal": final["sinal"],
            "preco": final["preco"],
            "stop": final["stop"],
            "alvo": final["alvo"],
            "rsi": float(final.get("confianca") or 50),
            "tendencia": final.get("estrutura", "SMC"),
            "motivo": "[IA] {} | liq: {} | zona: {}".format(
                str(final.get("motivo"))[:180],
                str(final.get("liquidez"))[:80],
                str(final.get("zona"))[:80]),
        }

    except Exception as e:
        logging.error("[IA] {} excecao: {}".format(par, e))
        _registrar(par, None, None, str(e), mercado)
        return None


def ia_ativa():
    return os.environ.get("AI_ENABLED") == "1" and bool(os.environ.get("GEMINI_API_KEY"))
