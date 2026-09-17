# futuro/monitor_futuro.py (MODO ESTUDO - BANCA FAKE $50 - SACA-LIQUIDEZ 4H HIBRIDO)
#
# Estrategia: Sweep 4H + CHoCH (validada em backtest)
# - Referencia: pavio da ultima vela 4H FECHADA
# - HIBRIDO: entra no RETEST do pavio (ordem limite, custo maker + sem slippage)
#   ate 4 velas apos o CHoCH; se nao voltar, entra a MERCADO no open do CHoCH (V1).
#   Backtest: +572 (bear) / +638 (bull) vs V1 puro, fracassa no flip, passa MC e
#   custos pessimistas (ramo "mercado" = V1 original como fallback).
# - Risco: SEMPRE $1 por trade (alavancagem matematica = 1% / distancia_do_stop)
# - Alvo: 3R = +$3
# - Banca fake: $50 inicial
# - Envia: imagem do grafico + texto para o Telegram
import requests
import os
import time
import json
import threading
from datetime import datetime, timezone

from telegram import enviar_mensagem, enviar_foto

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BOT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "banca_fake.json")
IMG_DIR = os.path.join(LOG_DIR, "img")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)

# ---------------- CONFIG --------------------
MOEDAS = ["BTCUSDT", "COLLECTUSDT", "BTWUSDT", "UAIUSDT", "HEMIUSDT", "STABLEUSDT",
          "1000PEPEUSDT", "ZAMAUSDT", "ZECUSDT", "SOLUSDT", "NEARUSDT", "BABYUSDT",
          "1000SATSUSDT", "NEIROUSDT", "DOGSUSDT", "PUMPUSDT", "AKEUSDT", "XPINUSDT",
          "TOSHIUSDT", "TURBOUSDT", "BOMEUSDT", "NOTUSDT", "1000SHIBUSDT", "DOGEUSDT",
          "GALAUSDT", "1000BONKUSDT", "MEMEUSDT", "HOTUSDT", "MEWUSDT", "XVGUSDT",
          "SPELLUSDT", "HMSTRUSDT"]
INTERVALO = "4h"
LOOP_SEG = int(os.environ.get("SACA_LOOP_SEG", "300"))
BANCA_INICIAL = float(os.environ.get("SACA_BANCA_INICIAL", "50"))
RISCO_USD = float(os.environ.get("SACA_RISCO", "1"))
ALVO_R = float(os.environ.get("SACA_ALVO_R", "3"))
TIME_EXIT = int(os.environ.get("SACA_TIME_EXIT", "8"))  # velas apos entrada
MAXR = 0.03  # distancia do stop maxima (3%)
NOTIONAL_BASE = 100.0  # posicao base com stop de 1%

# ---------------- CUSTOS REAIS DE FUTUROS ----------------
# Binance futuros USDT: taker 0.05% / maker 0.02% (VIP0), slippage estimado, funding ~0.01%/8h
TAKER_FEE = 0.0005      # entrada/saida a mercado
MAKER_FEE = 0.0002      # se entrar com limite (nao usado por padrao)
SLIPPAGE = 0.0008       # derrapagem a mercado
FUNDING_RATE = 0.0001   # financimento medio por 8h
FUNDING_H = 8           # intervalo do funding
HORAS_POR_VELA = 4      # candles 4H

# ---------------- FETCH BINANCE -------------
def fetch_klines(symbol, intervalo, start_ms=None, limit=1000):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": intervalo, "limit": limit}
    if start_ms:
        params["startTime"] = int(start_ms)
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def dados_4h(symbol, n_barras=300):
    """Retorna listas O/H/L/C/T do 4H, tempo agora incluido do ultimo candle."""
    out = []
    cur = None
    total = 0
    while total < n_barras:
        d = fetch_klines(symbol, INTERVALO, start_ms=cur)
        if not d:
            break
        out.extend(d)
        total += len(d)
        nxt = int(d[-1][0]) + 1
        if nxt <= (cur or 0):
            break
        cur = nxt
    out = out[-n_barras:]
    O = [float(x[1]) for x in out]
    H = [float(x[2]) for x in out]
    L = [float(x[3]) for x in out]
    C = [float(x[4]) for x in out]
    T = [int(x[0]) for x in out]
    return O, H, L, C, T


# ---------------- MOTOR + ENTRADA HIBRIDA (SWEEP 4H + CHoCH + RETEST) -------------
def buscar_sinais(O, H, L, C):
    """Retorna lista de (idx_entry, entry, stop, side, pavio) nos moldes do backtest V1.
    idx_entry = candle do CHoCH confirmado; pavio = referencia furada (H ou L da vela anterior ao sweep)."""
    n = len(O)
    sinais = []
    for i in range(1, n - 2):
        sh = (H[i] > H[i - 1]) and (C[i] < H[i - 1]) and (C[i] < O[i])
        lg = (L[i] < L[i - 1]) and (C[i] > L[i - 1]) and (C[i] > O[i])
        if sh and C[i + 1] < L[i]:
            pavio = H[i - 1]
            stop = pavio * 1.001
            entry = O[i + 1]
            if 0 < abs(entry - stop) / entry <= MAXR:
                sinais.append((i + 1, entry, stop, "S", pavio))
        if lg and C[i + 1] > H[i]:
            pavio = L[i - 1]
            stop = pavio * 0.999
            entry = O[i + 1]
            if 0 < abs(entry - stop) / entry <= MAXR:
                sinais.append((i + 1, entry, stop, "L", pavio))
    return sinais


RETRASO_RETEST = 4  # velas 4H de janela para o retest preencher


def decidir_entrada(sinal, O, H, L, C):
    """HIBRIDO: se o preco VOLTAR ao pavio dentro de RETRASO_RETEST velas apos o CHoCH,
    entra LIMITE no pavio (maker, sem slippage). Caso contrario, entra a MERCADO no
    open do CHoCH (taker, = V1 original como fallback). Retorna
    (entry, stop, idx_start, modo) com modo em {'limite','mercado'}."""
    idx_entry, entry_v1, stop_v1, side, pavio = sinal
    n = len(O)
    for j in range(idx_entry + 1, min(idx_entry + 1 + RETRASO_RETEST, n)):
        if side == "S" and H[j] >= pavio:
            stop = pavio * 1.001
            return pavio, stop, j, "limite"
        if side == "L" and L[j] <= pavio:
            stop = pavio * 0.999
            return pavio, stop, j, "limite"
    return entry_v1, stop_v1, idx_entry, "mercado"


# ---------------- BANCA FAKE -------------
def carregar_banca():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    return {"banca": BANCA_INICIAL, "trades": [], "ultimo_sinal": {}}


def salvar_banca(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def computar_resultado(entry, stop, side, idx_start, O, H, L, C):
    """Resolve o trade a partir de idx_start (vela da entrada real — retest ou mercado),
    com time exit (8 velas), retorna (resultado, preco_saida, idx_fim)."""
    n = len(O)
    tgt = entry - ALVO_R * abs(entry - stop) if side == "S" else entry + ALVO_R * abs(entry - stop)
    fim = min(idx_start + TIME_EXIT, n - 1)
    for j in range(idx_start + 1, fim + 1):
        if side == "S":
            if L[j] <= tgt:
                return "WIN", tgt, j
            if H[j] >= stop:
                return "LOSS", stop, j
        else:
            if H[j] >= tgt:
                return "WIN", tgt, j
            if L[j] <= stop:
                return "LOSS", stop, j
    return "TIME", C[fim], fim


def calc_alavancagem(entry, stop):
    dist = abs(entry - stop) / entry
    lev = 0.01 / dist if dist > 0 else 1.0
    notional = NOTIONAL_BASE * lev
    return lev, notional, dist


def calc_custos(entry, saida, side, notional, n_velas_posicao, entra_limit=False):
    """Custos reais: fee entrada (maker se limit, senq taker) + saida taker sempre
    (conservador) + slippage so na saida (entrada limite nao derrapa) + funding por tempo.
    Retorna dict com cada componente e total em USD."""
    fee_entrada = notional * (MAKER_FEE if entra_limit else TAKER_FEE)
    fee_saida = notional * TAKER_FEE
    slippage_custo = notional * SLIPPAGE  # so na saida (conservador)
    horas = n_velas_posicao * HORAS_POR_VELA
    n_fundings = int(horas // FUNDING_H)
    funding_custo = notional * FUNDING_RATE * n_fundings
    total = fee_entrada + fee_saida + slippage_custo + funding_custo
    return {
        "fee_entrada": fee_entrada, "fee_saida": fee_saida,
        "slippage": slippage_custo, "funding": funding_custo,
        "total": total, "n_fundings": n_fundings, "horas": horas,
    }


# ---------------- IMAGEM DO GRAFICO ------------
def gerar_imagem(symbol, side, entry, stop, alvo, O, H, L, C, T, idx_entry, idx_start=None, pavio=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    if idx_start is None:
        idx_start = idx_entry
    n = len(C)
    i0 = max(0, idx_start - 8)
    i1 = min(n, idx_start + 12)
    fig, ax = plt.subplots(figsize=(8, 5))
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")

    mm = max(H[i0:i1])
    mn = min(L[i0:i1])
    pad = (mm - mn) * 0.30
    for i in range(i0, i1):
        color = "#26a69a" if C[i] >= O[i] else "#ef5350"
        ax.plot([i, i], [L[i], H[i]], color=color, lw=1.1, zorder=3)
        lo, hi = min(O[i], C[i]), max(O[i], C[i])
        ax.add_patch(mpatches.Rectangle((i - 0.30, lo), 0.60, max(hi - lo, 0.0000001), color=color, zorder=4))

    # referencia = pavio da vela 4H que foi furada (a fechada anterior ao sweep)
    ref = pavio if pavio is not None else (H[idx_entry - 1] if side == "S" else L[idx_entry - 1])
    ax.axhline(ref, color="#fdd835", ls="--", lw=1.4, zorder=2)
    ax.text(i0, ref, "  pavio 4H ({:.6g})".format(ref), color="#fdd835", fontsize=8, fontweight="bold")

    ax.hlines(stop, idx_start - 0.9, idx_start + 0.9, color="#ef5350", lw=2.2, zorder=5)
    ax.text(idx_start + 1.0, stop, "STOP {:.6g}".format(stop), color="#ef5350", fontsize=8, fontweight="bold", va="center")
    ax.hlines(alvo, idx_start - 0.9, idx_start + 0.9, color="#26a69a", lw=2.2, zorder=5)
    ax.text(idx_start + 1.0, alvo, "ALVO {:.6g}".format(alvo), color="#26a69a", fontsize=8, fontweight="bold", va="center")

    colE = "#ef5350" if side == "S" else "#26a69a"
    ax.scatter([idx_start], [entry], color=colE, s=140, zorder=6, edgecolor="white", marker="o" if side == "L" else "v")
    ax.text(idx_start, entry - pad * 0.18 if side == "L" else entry + pad * 0.18,
            "ENTRADA {:.6g}".format(entry), color="white", fontsize=9,
            fontweight="bold", ha="center")

    modo_lbl = "RETEST" if idx_start != idx_entry else "CHoCH"
    dirn = "SHORT" if side == "S" else "LONG"
    ax.set_title("{} {}4H - SWEEP {} + {} | ENTRY {:.6g}".format(symbol, "{}".format(INTERVALO), dirn, modo_lbl, entry),
                 color="white", fontsize=11, fontweight="bold")
    ax.set_ylim(mn - pad, mm + pad)
    ax.axis("off")
    ax.set_xlim(i0 - 0.5, i1 + 2.5)
    plt.tight_layout()
    caminho = os.path.join(IMG_DIR, "{}_sinal.png".format(symbol))
    plt.savefig(caminho, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    return caminho


# ---------------- TEXTO TELEGRAM ------------
def formatar_sinal(symbol, side, entry, stop, alvo, lev, notional, banca, n_trade, modo="mercado"):
    tag = "LONG (COMPRA)" if side == "L" else "SHORT (VENDA)"
    emoji = "🔺" if side == "L" else "🔻"
    lado = "acima" if side == "S" else "abaixo"
    if modo == "limite":
        modo_txt = "retest do pavio (ordem LIMITE) 🎯"
    else:
        modo_txt = "CHoCH (entrada a MERCADO)"
    texto = (
        "{e} SWEEP 4H - {tag}\n"
        "📊 {sym}\n"
        "\n"
        "💥 Furo do pavio 4H ({lado}) + CHoCH confirmado\n"
        "➡️ Entrada: {modo_txt}\n"
        "🎯 Entrada: {entry:.6g}\n"
        "🛑 Stop: {stop:.6g}\n"
        "✅ Alvo: {alvo:.6g} (3R)\n"
        "\n"
        "⚡ Alavancagem: {lev:.2f}x (posicao ${notional:.2f})\n"
        "💰 Banca fake: ${banca:.2f} | trade #{num}\n"
        "🕐 {hora} UTC"
    ).format(
        e=emoji, tag=tag, sym=symbol, lado=lado,
        modo_txt=modo_txt, entry=entry, stop=stop, alvo=alvo,
        lev=lev, notional=notional, banca=banca, num=n_trade,
        hora=datetime.now(timezone.utc).strftime("%d/%m %H:%M"),
    )
    return texto


def formatar_resultado(symbol, side, res, entry, saida, pl_usd, pl_bruto, banca, custos, modo="mercado"):
    if res == "WIN":
        tag, emoji = "TAKE PROFIT", "✅"
    elif res == "LOSS":
        tag, emoji = "STOP LOSS", "❌"
    else:
        tag, emoji = "TIME OUT (8 velas)", "⏰"
    dirn = "LONG" if side == "L" else "SHORT"
    entrada_lbl = "Entrada LIMITE (retest)" if modo == "limite" else "Entrada MERCADO (CHoCH)"
    texto = (
        "{e} {sym} | {dirn} | {tag}\n"
        "{entrada_lbl}\n"
        "Entrada: {en:.6g} | Saida: {saida:.6g}\n"
        "P/L bruto: ${bruto:+.2f}\n"
        "Custos:"
    ).format(e=emoji, sym=symbol, dirn=dirn, tag=tag, entrada_lbl=entrada_lbl, en=entry,
             saida=saida, bruto=pl_bruto)
    if custos:
        fee_entrada = "Fee maker entrada" if modo == "limite" else "Fee taker entrada"
        texto += (
            "\n  • {fee}: ${fe:.4f}"
            "\n  • Fee taker saida: ${fs:.4f}"
            "\n  • Slippage (saida): ${sl:.4f}"
            "\n  • Funding ({nf}x8h): ${fd:.4f}"
            "\n  • Total custos: ${to:.4f}"
            "\nP/L liquido: ${pl:+.2f}"
            "\n💰 Banca fake: ${banca:.2f}"
        ).format(
            fee=fee_entrada, fe=custos["fee_entrada"], fs=custos["fee_saida"],
            sl=custos["slippage"], fd=custos["funding"],
            nf=custos["n_fundings"], to=custos["total"],
            pl=pl_usd, banca=banca,
        )
    else:
        texto += "\nP/L liquido: ${pl:+.2f}\n💰 Banca fake: ${banca:.2f}".format(
            pl=pl_usd, banca=banca)
    return texto


# ---------------- MONITOR ----------------
def monitorar():
    print("[Saca-Liquidez 4H] Modo estudo - banca fake ${:.2f}".format(BANCA_INICIAL))
    while True:
        try:
            banca_data = carregar_banca()
            banca = float(banca_data.get("banca", BANCA_INICIAL))
            trades = banca_data.get("trades", [])
            n_trade = len(trades) + 1
            ultimo = banca_data.get("ultimo_sinal", {})

            for symbol in MOEDAS:
                try:
                    O, H, L, C, T = dados_4h(symbol)
                except Exception as e:
                    print("[{}] fetch falhou: {}".format(symbol, e))
                    continue
                sinais = buscar_sinais(O, H, L, C)
                if not sinais:
                    continue
                sinal = sinais[-1]
                idx_entry, entry_v1, stop_v1, side, pavio = sinal
                # evita repetir mesmo sinal
                chave = "{}:{}:{}".format(symbol, side, T[idx_entry])
                if ultimo.get(symbol) == chave:
                    continue

                # HIBRIDO: tenta retest do pavio (maker); fallback = mercado (V1)
                entry, stop, idx_start, modo = decidir_entrada(sinal, O, H, L, C)

                lev, notional, dist = calc_alavancagem(entry, stop)
                alvo = entry - ALVO_R * abs(entry - stop) if side == "S" else entry + ALVO_R * abs(entry - stop)

                print("[{}] SINAL {} ent={:.6g} stop={:.6g} [{}] lev={:.2f}x notional=${:.2f}".format(
                    symbol, side, entry, stop, modo, lev, notional))

                # resolve o trade para anunciar (ja roda sobre historico)
                res, saida, idx_fim = computar_resultado(entry, stop, side, idx_start, O, H, L, C)

                # P/L com risco fixo $1 (bruto, antes dos custos)
                mult = -1 if side == "S" else 1
                if res == "WIN":
                    pl_bruto = ALVO_R * RISCO_USD
                elif res == "LOSS":
                    pl_bruto = -RISCO_USD
                else:
                    pl_bruto = mult * (saida - entry) / abs(entry - stop) * RISCO_USD

                # custos reais (entrada maker se limite; saida taker + funding por tempo)
                n_velas_pos = max(0, idx_fim - idx_start)
                custos = calc_custos(entry, saida, side, notional, n_velas_pos, entra_limit=(modo == "limite"))
                pl = pl_bruto - custos["total"]
                banca += pl

                # imagem + notificacao
                try:
                    img = gerar_imagem(symbol, side, entry, stop, alvo, O, H, L, C, T, idx_start, idx_entry, pavio)
                    texto = formatar_sinal(symbol, side, entry, stop, alvo, lev, notional, banca, n_trade, modo)
                    ok, msg = enviar_foto(img, caption=texto)
                    if ok:
                        print("[{}] foto enviada".format(symbol))
                    else:
                        print("[{}] falha foto: {}".format(symbol, msg))
                        ok2, msg2 = enviar_mensagem(texto)
                        print("[{}] fallback texto: {}".format(symbol, msg2))
                except Exception as e:
                    print("[{}] erro imagem/envio: {}".format(symbol, e))

                # guarda trade e banca
                trades.append({
                    "moeda": symbol, "lado": side, "entrada": entry, "stop": stop,
                    "alvo": alvo, "modo": modo, "alavancagem": round(lev, 2), "notional": round(notional, 2),
                    "resultado": res, "saida": saida,
                    "pl_bruto": round(pl_bruto, 2), "pl_liquido": round(pl, 2),
                    "custos": {k: round(v, 4) for k, v in custos.items() if isinstance(v, float)},
                    "n_velas": n_velas_pos,
                    "data_sinal": datetime.fromtimestamp(T[idx_entry] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "data_fim": datetime.fromtimestamp(T[idx_fim] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                })
                banca_data["banca"] = round(banca, 2)
                banca_data["ultimo_sinal"][symbol] = chave
                banca_data["trades"] = trades
                salvar_banca(banca_data)

                # notificacao de resultado (so quando concluir)
                okr, msgr = enviar_mensagem(formatar_resultado(
                    symbol, side, res, entry, saida, pl, pl_bruto, banca, custos, modo))
                print("[{}] resultado {} bruto={:+.2f} custos={:.2f} liq={:+.2f} (tg {})".format(
                    symbol, res, pl_bruto, custos["total"], pl, msgr))

            time.sleep(LOOP_SEG)
        except Exception as e:
            print("[monitor] erro geral: {}".format(e))
            time.sleep(LOOP_SEG)


# ---------------- SERVIDOR WEB (health/status/debug p/ Render) -------------
def web_server():
    try:
        from flask import Flask, jsonify
    except Exception:
        return
    app = Flask(__name__)

    @app.route("/")
    def hello():
        return "Saca-Liquidez 4H"

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/status")
    def status():
        try:
            b = carregar_banca()
            trades = b.get("trades", [])
            wins = sum(1 for t in trades if t.get("resultado") == "WIN")
            losses = sum(1 for t in trades if t.get("resultado") == "LOSS")
            pl = sum(t.get("pl_liquido", 0) for t in trades)
            n = len(trades)
            return jsonify({
                "banca": round(float(b.get("banca", BANCA_INICIAL)), 2),
                "n_trades": n,
                "wins": wins,
                "losses": losses,
                "pl_liquido": round(pl, 2),
                "win_rate": round(100.0 * wins / n, 1) if n else 0,
                "estrategia": "Saca-Liquidez 4H (retest+mercado)",
                "ultimo_sinal": b.get("ultimo_sinal", {}),
            })
        except Exception as e:
            return jsonify({"erro": str(e)}), 500

    @app.route("/debug")
    def debug():
        try:
            logs = []
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, "r") as f:
                    b = json.load(f)
                trades = b.get("trades", [])
                logs = [t.get("data_sinal", "") + " " + t.get("moeda", "") + " " +
                        t.get("lado", "") + " " + str(t.get("resultado", "")) for t in trades[-20:]]
            return jsonify({"banca": carregar_banca().get("banca"), "trades_recentes": logs})
        except Exception as e:
            return jsonify({"erro": str(e)}), 500

    port = int(os.environ.get("PORT", "10000"))
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        print("[web] servidor falhou: {}".format(e))


if __name__ == "__main__":
    threading.Thread(target=web_server, daemon=True).start()
    monitorar()