"""
Cerebro de IA para decisoes de trading (SMC).
Recebe dados multi-timeframe da Binance, aplica o framework SMC via LLM
(Gemini) e retorna um sinal estruturado com raciocinio.

Env vars:
    AI_ENABLED=1          -> ativa o cerebro
    GEMINI_API_KEY=...    -> chave da API (aistudio.google.com)
    AI_MODEL=...          -> default: gemini-2.5-flash
"""

import os
import json
import logging
from datetime import datetime

import requests

from core.dados import buscar_historico

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

MODELO = os.environ.get("AI_MODEL", "gemini-2.5-flash")

# ---------------------------------------------------------------------------
# CONHECIMENTO SMC condensado (fonte: docs/smc_knowledge.md - Azvdou/ICT)
# ---------------------------------------------------------------------------

PROMPT_SISTEMA = """Voce e um trader profissional de day trade especialista em Smart Money Concepts (SMC/ICT).
Analise os dados de mercado fornecidos e decida se ha uma operacao de ALTA qualidade agora.

FRAMEWORK DE ANALISE (nesta ordem):
1. ESTRUTURA: identifique HH/HL (alta) ou LH/LL (baixa) em cada timeframe. Ultimo evento foi BOS (continuacao) ou CHoCH/MSS (reversao)?
2. LIQUIDEZ: onde estao os stops? Equal highs/lows, topos/fundos recentes (BSL acima, SSL abaixo). Houve SWEEP recente (pavio capturou stops e reverteu)?
3. ZONAS: existe OB valido (ultima vela oposta ANTES de impulso com displacement que causou BOS) ou FVG (gap de 3 velas) nao mitigado perto do preco?
4. PREMIUM/DISCOUNT: preco esta na metade inferior (discount = compra ok) ou superior (premium = venda ok) do range atual?
5. CONFLUENCIA: os melhores trades tem 3+ fatores: sweep + zona (OB/FVG) + alinhamento com estrutura maior + confirmacao de reversao.
6. GESTAO: so proponha trade com risco/retorno minimo 1:2. Stop vai ALEM da zona/sweep (nao arbitrario). Alvo = liquidez oposta mais proxima.

REGRAS CRITICAS:
- Estrutura do timeframe MAIOR manda. Nunca compre contra tendencia de 4h forte.
- SEM confluencia clara = sinal NADA. Ficar de fora e uma decisao valida e frequente (trader profissional opera pouco).
- NUNCA invente niveis: use precos reais dos candles fornecidos.
- Voce esta sendo auditado: cada decisao fica registrada. Prefira precisao a quantidade.

RESPONDA APENAS COM JSON VALIDO neste formato exato:
{
  "sinal": "COMPRA" | "VENDA" | "NADA",
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


def coletar_contexto(par):
    """Monta o contexto multi-timeframe compacto de um par."""
    partes = ["PAR: {}".format(par)]

    for tf, n in (("4h", 40), ("1h", 50), ("15m", 60)):
        try:
            df = buscar_historico(par, tf, n)
            if df is None or len(df) == 0:
                continue
            partes.append("\n=== CANDLES {} (mais recentes por ultimo) ===".format(tf))
            partes.append(_fmt_candles(df, n))
        except Exception as e:
            partes.append("\n=== CANDLES {}: erro ({}) ===".format(tf, e))

    return "\n".join(partes)


def _validar(decisao, preco_ref):
    """Valida sanidade da decisao. Retorna (decisao_ok, erro_ou_none)."""
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

    if preco <= 0:
        return None, "preco <= 0"

    if sinal == "COMPRA":
        if not (0 < stop < preco < alvo):
            return None, "niveis inconsistentes p/ COMPRA (precisa stop<preco<alvo)"
    else:
        if not (0 < alvo < preco < stop):
            return None, "niveis inconsistentes p/ VENDA (precisa alvo<preco<stop)"

    risco = abs(preco - stop)
    retorno = abs(alvo - preco)
    if risco <= 0:
        return None, "risco zero"
    rr = retorno / risco
    if rr < 1.5:
        return None, "R:R {:.2f} abaixo do minimo 1.5".format(rr)

    decisao["preco"] = preco
    decisao["stop"] = stop
    decisao["alvo"] = alvo
    decisao["rr"] = round(rr, 2)
    return decisao, None


def _chamar_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, "GEMINI_API_KEY nao configurada"
    url = GEMINI_URL.format(model=MODELO, key=key)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 1024,
        },
    }
    resp = requests.post(url, json=body, timeout=60)
    if resp.status_code != 200:
        return None, "HTTP {}: {}".format(resp.status_code, resp.text[:300])
    data = resp.json()
    try:
        texto = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return None, "resposta sem texto: {}".format(json.dumps(data)[:300])
    return texto, None


LOG_IA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "ai_decisions.jsonl")


def _registrar(par, resultado_bruto, final, erro):
    try:
        os.makedirs(os.path.dirname(LOG_IA), exist_ok=True)
        registro = {
            "data": datetime.now().strftime("%d/%m %H:%M:%S"),
            "par": par,
            "erro": erro,
            "decisao_final": final,
            "resposta_bruta": (resultado_bruto or "")[:2000],
        }
        with open(LOG_IA, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception:
        pass


def analisar_com_ia(par):
    """
    Retorna dict no mesmo formato de spot.strategy.analisar():
    {"sinal": "COMPRA"/"VENDA", "preco", "stop", "alvo", "rsi", "tendencia", "motivo"}
    ou None se nao ha sinal / houve erro.
    """
    try:
        contexto = coletar_contexto(par)
        prompt = PROMPT_SISTEMA + "\n\nDADOS DE MERCADO:\n" + contexto
        bruto, erro_api = _chamar_gemini(prompt)

        if erro_api:
            logging.error("[IA] {} erro api: {}".format(par, erro_api))
            _registrar(par, None, None, erro_api)
            return None

        try:
            decisao = json.loads(bruto)
        except json.JSONDecodeError:
            logging.error("[IA] {} json invalido".format(par))
            _registrar(par, bruto, None, "json invalido")
            return None

        preco_ref = 0.0
        try:
            df = buscar_historico(par, "1m", 2)
            preco_ref = float(df["close"].iloc[-1])
        except Exception:
            pass

        final, erro_val = _validar(decisao, preco_ref)
        if erro_val:
            logging.info("[IA] {} descartado: {}".format(par, erro_val))
            _registrar(par, bruto, None, erro_val)
            return None

        _registrar(par, bruto, final, None)

        if final["sinal"] == "NADA":
            return None

        logging.info("[IA] SINAL {} {} conf={} rr={} | {}".format(
            final["sinal"], par, final.get("confianca"), final.get("rr"),
            str(final.get("motivo"))[:120]))

        return {
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
        _registrar(par, None, None, str(e))
        return None


def ia_ativa():
    return os.environ.get("AI_ENABLED") == "1" and bool(os.environ.get("GEMINI_API_KEY"))
