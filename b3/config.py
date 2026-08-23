import os
import json
from datetime import datetime, date, time as dtime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")

ATIVO = os.environ.get("B3_ATIVO", "WDO")
CONTRATOS = int(os.environ.get("B3_CONTRATOS", "1"))

# WDO: R$10/ponto (tick 0,5 = R$5) | WIN: R$0,20/ponto (tick 5 pts = R$1)
VALOR_PONTO = float(os.environ.get("B3_VALOR_PONTO", "10"))
CUSTO_TRADE = float(os.environ.get("B3_CUSTO_TRADE", "1.0"))
BANCO_INICIAL = float(os.environ.get("B3_BANCO_INICIAL", "500"))

INTERVALO = "5m"
INTERVALO_MONITOR = int(os.environ.get("AI_INTERVALO", "300"))
MERCADO = "b3"

MAX_SINAIS_DIA = int(os.environ.get("B3_MAX_SINAIS_DIA", "3"))
STOP_DIARIO_PCT = float(os.environ.get("B3_STOP_DIARIO_PCT", "10"))
META_DIARIA_PCT = float(os.environ.get("B3_META_DIARIA_PCT", "20"))
RISCO_MAX_TRADE_REAIS = float(os.environ.get("B3_RISCO_MAX_TRADE_REAIS", "25"))

JANELAS = [
    ("09:00", "10:30"),
    ("10:30", "12:30"),
    ("15:00", "17:00"),
]
NOMES_JANELAS = ["ABERTURA BRASIL", "ABERTURA NY", "TARDE"]
FECHAMENTO_FORCADO = dtime(17, 45)
FIM_SESSAO = dtime(18, 30)

STUDY_MODE = os.environ.get("B3_STUDY_MODE", "1") == "1"
INTERVALO_ESTUDO = 1800

CALENDARIO_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "calendario_b3.json",
)


def agora_brt():
    return datetime.now(TZ)


def _parse_hhmm(txt):
    h, m = txt.strip().split(":")
    return dtime(int(h), int(m))


def dia_util(dt=None):
    dt = dt or agora_brt()
    return dt.weekday() < 5


def janela_atual(dt=None):
    """Nome da killzone atual ou None se fora de janela."""
    dt = dt or agora_brt()
    if not dia_util(dt):
        return None
    hora = dt.time()
    for i, (ini, fim) in enumerate(JANELAS):
        if _parse_hhmm(ini) <= hora < _parse_hhmm(fim):
            return NOMES_JANELAS[i]
    return None


def em_blackout(dt=None):
    """True perto de evento macro (env B3_BLACKOUT + docs/calendario_b3.json)."""
    dt = dt or agora_brt()
    dias = {0: "SEG", 1: "TER", 2: "QUA", 3: "QUI", 4: "SEX", 5: "SAB", 6: "DOM"}

    for item in (os.environ.get("B3_BLACKOUT") or "").split(","):
        partes = item.strip().split()
        if len(partes) != 2 or partes[0].upper() != dias[dt.weekday()]:
            continue
        ini, fim = partes[1].split("-")
        if _parse_hhmm(ini) <= dt.time() <= _parse_hhmm(fim):
            return True

    try:
        with open(CALENDARIO_FILE, encoding="utf-8") as f:
            cal = json.load(f)
        for ev in cal.get("eventos", []):
            data_ev = datetime.strptime(ev["data"], "%d/%m/%Y").date()
            if data_ev != dt.date():
                continue
            margem = timedelta(minutes=30)
            hora_ev = dt.replace(
                hour=int(ev["hora"][:2]), minute=int(ev["hora"][3:5]),
                second=0, microsecond=0,
            )
            if hora_ev - margem <= dt <= hora_ev + margem:
                return True
        if dt.date().strftime("%d/%m/%Y") in [f.strftime("%d/%m/%Y")
                                              for f in _feriados(cal)]:
            return True
    except Exception:
        pass
    return False


def _feriados(cal):
    lista = []
    for txt in cal.get("feriados", []):
        try:
            lista.append(datetime.strptime(txt, "%d/%m/%Y").date())
        except Exception:
            pass
    return lista


def pode_operar_agora():
    """(pode_sinalizar, motivo). Fechamento forcado e fim de sessao bloqueiam."""
    agora = agora_brt()
    if not dia_util(agora):
        return False, "fim de semana"
    if em_blackout(agora):
        return False, "blackout macro"
    if agora.time() >= FECHAMENTO_FORCADO:
        return False, "pos-fechamento forcado"
    janela = janela_atual(agora)
    if not janela:
        return False, "fora de killzone"
    return True, janela
