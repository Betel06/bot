"""
Le o historico de operacoes direto do chat com o bot no Telegram (via MTProto).
Fonte da verdade permanente: cada sinal e resultado virou mensagem no chat.
"""
import os
import re
import time
from datetime import datetime

PEER_BOT_ID = 8972102244
TTL_CACHE = 180

_CACHE = {"ts": 0.0, "dados": None}

RE_RESULTADO = re.compile(r"(TRADER SPOT|TRADER FUTURO)\s*\|\s*(WIN|LOSS)")
RE_PAR_DIR = re.compile(r"Par:\s*(\w+)\s*\((\w+)\)")
RE_PL = re.compile(r"P/L:\s*\$([+-]?[\d.,]+)")
RE_ALVO = re.compile(r"ALVO:\s*\$([\d.,]+)")
RE_STOP = re.compile(r"STOP:\s*\$([\d.,]+)")
RE_ENTRADA_FUT = re.compile(r"Entrada:\s*\$([\d.,]+)")
RE_PRECO_SPOT = re.compile(r"Preco:\s*\$([\d.,]+)")


def configurado():
    return bool(os.environ.get("TELETHON_SESSION"))


def _cliente():
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession
    api_id = int(os.environ.get("TG_API_ID") or 36884185)
    api_hash = os.environ.get("TG_API_HASH") or ""
    sess = os.environ.get("TELETHON_SESSION") or ""
    return TelegramClient(StringSession(sess), api_id, api_hash)


def _parse_mensagem(msg_text, msg_date, resultados, abertas, fechados):
    t = msg_text or ""
    primeira = t.split("\n")[0] if t else ""

    res = RE_RESULTADO.search(primeira)
    if res:
        bot = "spot" if res.group(1) == "TRADER SPOT" else "futuro"
        win = res.group(2) == "WIN"
        mpar = RE_PAR_DIR.search(t)
        mpl = RE_PL.search(t)
        par = mpar.group(1) if mpar else "?"
        direcao = mpar.group(2) if mpar else ""
        try:
            lucro = float(mpl.group(1).replace(",", ".")) if mpl else 0.0
        except ValueError:
            lucro = 0.0
        op = {
            "par": par,
            "direcao": direcao,
            "tipo": "TAKE PROFIT" if win else "STOP LOSS",
            "lucro": lucro,
            "data": msg_date.strftime("%d/%m %H:%M"),
        }
        resultados[bot].append(op)
        fechados.add((bot, par))
        return

    if "Entrada:" in t or "Preco:" in t:
        if "ALVO" not in t or "STOP" not in t:
            return
        if "TRADER FUTURO" in primeira:
            bot = "futuro"
            mdir = re.search(r"\b(LONG|SHORT)\b", t)
            direcao = {"LONG": "COMPRA", "SHORT": "VENDA"}.get(
                mdir.group(1), "COMPRA") if mdir else "COMPRA"
            ment = RE_ENTRADA_FUT.search(t)
        elif "TRADER SPOT" in primeira:
            bot = "spot"
            mdir = re.search(r"\b(COMPRA|VENDA)\b", primeira + "\n" + t[:200])
            direcao = mdir.group(1) if mdir else "COMPRA"
            ment = RE_PRECO_SPOT.search(t)
        else:
            return

        par_nome = None
        mpar = re.search(r"Par:\s*(\w+)", t)
        if mpar:
            par_nome = mpar.group(1)
        elif bot == "spot":
            m2 = re.search(r"(?:COMPRA|VENDA)\s*[🔼🔽]\s*([A-Z0-9]+)", t[:300])
            if m2:
                par_nome = m2.group(1)
        if not par_nome:
            return

        malvo = RE_ALVO.search(t)
        mstop = RE_STOP.search(t)

        def _num(mobj, padrao=0.0):
            try:
                return float(mobj.group(1).replace(",", ".")) if mobj else padrao
            except ValueError:
                return padrao

        chave = (bot, par_nome)
        if chave not in fechados:
            abertas[chave] = {
                "bot": bot,
                "par": par_nome,
                "direcao": direcao,
                "entrada": _num(ment),
                "stop": _num(mstop),
                "alvo": _num(malvo),
                "data": msg_date.strftime("%d/%m %H:%M"),
            }


def ler_estado_do_chat(limite=400, forcar=False):
    """
    Retorna:
    {
      "spot":   {"wins": n, "losses": n, "pl": x, "historico": [ops]},
      "futuro": {...},
      "abertas": [ {bot, par, direcao, entrada, stop, alvo, data} ],
      "quando": "dd/mm HH:MM"
    }
    """
    agora = time.time()
    if not forcar and _CACHE["dados"] and agora - _CACHE["ts"] < TTL_CACHE:
        return _CACHE["dados"]

    resultados = {"spot": [], "futuro": []}
    abertas = {}
    fechados = set()

    with _cliente() as client:
        alvo_ent = None
        for d in client.iter_dialogs():
            if d.id == PEER_BOT_ID:
                alvo_ent = d.entity
                break
        if alvo_ent is None:
            raise RuntimeError("dialogo com o bot nao encontrado")

        for m in client.iter_messages(alvo_ent, limit=limite):
            _parse_mensagem(m.message, m.date, resultados, abertas, fechados)

    dados = {"abertas": [], "quando": datetime.now().strftime("%d/%m %H:%M")}
    for bot in ("spot", "futuro"):
        ops = list(reversed(resultados[bot]))
        wins = sum(1 for o in ops if o["tipo"] == "TAKE PROFIT")
        losses = len(ops) - wins
        pl = sum(o["lucro"] for o in ops)
        dados[bot] = {"wins": wins, "losses": losses,
                      "pl": round(pl, 4), "historico": ops}
    for (bot, _par), info in abertas.items():
        dados["abertas"].append(info)

    _CACHE["ts"] = agora
    _CACHE["dados"] = dados
    return dados
