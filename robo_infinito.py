"""
ROBO INFINITO - Agente autonomo local (sem creditos, sem API de chat)
Roda em loop infinito no PC, monitora bots Render + Huntera e usa
Ollama local (qwen3:4b) como cerebro de decisao.

Uso: python robo_infinito.py
Parar: Ctrl+C ou fechar o terminal.
"""

import os
import sys
import time
import json
import logging
import threading
import subprocess

import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
MODELO = os.environ.get("ROBO_MODELO", "qwen3:4b")

INTERVALO = int(os.environ.get("ROBO_INTERVALO", "300"))  # ciclo a cada 5 min
PASTA_BOT = r"C:\Users\danie\Documents\BOT"
PASTA_HUNTERA = r"C:\Users\danie\Documents\huntera-bot"
ESTADO_HUNTERA = os.path.join(PASTA_HUNTERA, "estado.json")
LOG_DIR = os.path.join(PASTA_BOT, "logs")
LOG_ARQ = os.path.join(LOG_DIR, "robo_infinito.log")

_diag_rodando = False

# janela oculta para QUALQUER processo filho (pythonw nao tem console:
# sem essa flag o wmic/taskkill abrem janela de cmd visivel na tela)
CREATE_HIDDEN = subprocess.CREATE_NO_WINDOW

BOTS_RENDER = [
    ("bot-spot", "https://bot-spot.onrender.com/health"),
    ("bot-futuro", "https://bot-futuro-acdj.onrender.com/health"),
    ("bot-b3", "https://bot-b3.onrender.com/"),
]

# ---------------------------------------------------------------------------
# LOG
# ---------------------------------------------------------------------------
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_ARQ, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("robo")


# ---------------------------------------------------------------------------
# CEREBRO LOCAL (Ollama) - sem limite de credito
# ---------------------------------------------------------------------------
def pensar(pergunta, timeout=90):
    """Pergunta ao Ollama local. Retorna texto ou None."""
    try:
        # qwen3: desativa cadeia de pensamento p/ resposta rapida
        prompt = "/no_think\n" + pergunta if "qwen3" in MODELO else pergunta
        resp = requests.post(OLLAMA_URL, json={
            "model": MODELO,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }, timeout=timeout)
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
        log.warning("Ollama HTTP {}: {}".format(resp.status_code, resp.text[:100]))
    except Exception as e:
        log.warning("Ollama indisponivel: {}".format(e))
    return None


# ---------------------------------------------------------------------------
# MONITOR RENDER (keep-alive + deteccao de queda)
# ---------------------------------------------------------------------------
def checar_render():
    resultados = {}
    for nome, url in BOTS_RENDER:
        try:
            r = requests.get(url, timeout=30)
            resultados[nome] = "ON" if r.status_code == 200 else "HTTP {}".format(r.status_code)
        except Exception as e:
            resultados[nome] = "OFF ({})".format(str(e)[:40])
    return resultados


# ---------------------------------------------------------------------------
# MONITOR HUNTERA (detecta zumbi: processo vivo mas estado parado > 5 min)
# ---------------------------------------------------------------------------
def idade_estado_huntera():
    """Segundos desde a ultima modificacao do estado.json (None se nao existe)."""
    if not os.path.exists(ESTADO_HUNTERA):
        return None
    return time.time() - os.path.getmtime(ESTADO_HUNTERA)


def node_vivo():
    try:
        saida = subprocess.run(
            ["wmic", "process", "where", "name='node.exe'", "get", "commandline"],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_HIDDEN,
        ).stdout.lower()
        return "bot.js" in saida
    except Exception:
        return False


def religar_huntera(motivo):
    """MODO MANUAL: so registra no log. Nada abre sozinho."""
    log.warning("[HUNTERA] {} (auto-religa desativado; use 'Iniciar Huntera' manualmente)".format(motivo))


def checar_huntera():
    idade = idade_estado_huntera()
    vivo = node_vivo()

    if not vivo:
        religar_huntera("processo node/bot.js ausente")
        return "parado (sem processo)"
    if idade is None:
        return "processo vivo (sem estado.json)"
    if idade > 300:  # 5 min sem tocar o estado = zumbi
        religar_huntera("zumbi: estado.json parado ha {:.0f}s".format(idade))
        return "zumbi (estado parado {:.0f}s)".format(idade)
    return "ok (estado {:.0f}s)".format(idade)


# ---------------------------------------------------------------------------
# DECISAO DA IA LOCAL: resumo do ciclo + diagnostico quando algo erra
# ---------------------------------------------------------------------------
def diagnosticar(render, huntera_status):
    problemas = []
    for nome, st in render.items():
        if not st.startswith("ON"):
            problemas.append("{} esta {}".format(nome, st))
    if huntera_status.startswith(("zumbi", "falha")):
        problemas.append("huntera {}".format(huntera_status))

    if not problemas:
        return None

    contexto = (
        "Voce e um agente de TI autonomo rodando num PC Windows. "
        "Estado atual dos servicos:\n"
        + "\n".join("- {}: {}".format(n, s) for n, s in render.items())
        + "\n- huntera: " + huntera_status
        + "\n\nProblemas detectados: " + "; ".join(problemas)
        + "\nResponda em ate 3 linhas: qual a causa mais provavel e a acao recomendada? "
          "Seja direto, sem introducao."
    )
    return pensar(contexto)


# ---------------------------------------------------------------------------
# LOOP INFINITO
# ---------------------------------------------------------------------------
def _diagnostico_em_thread(render, status_h):
    """IA local em thread separada: nunca trava o monitoramento."""
    global _diag_rodando
    if _diag_rodando:
        return  # anterior ainda processando; nao empilhar
    _diag_rodando = True
    try:
        dica = diagnosticar(render, status_h)
        if dica:
            log.info("[IA LOCAL]\n" + dica)
    except Exception as e:
        log.warning("diagnostico falhou (ignorado): {}".format(e))
    finally:
        _diag_rodando = False


def ciclo():
    render = checar_render()
    status_h = checar_huntera()

    linha_render = " | ".join("{}:{}".format(n, s) for n, s in render.items())
    log.info("[CICLO] render[{}] huntera[{}]".format(linha_render, status_h))

    threading.Thread(
        target=_diagnostico_em_thread, args=(render, status_h), daemon=True
    ).start()


def main():
    # instancia unica: evita dois robos brigando pelos mesmos processos
    lock = os.path.join(LOG_DIR, "robo_infinito.lock")
    try:
        if os.path.exists(lock):
            idade_lock = time.time() - os.path.getmtime(lock)
            if idade_lock < 600:  # lock com menos de 10 min = outro robo vivo
                log.warning("outro robo ja esta rodando (lock {:.0f}s). Saindo.".format(idade_lock))
                return
        with open(lock, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception as e:
        log.warning("lock falhou (seguindo mesmo assim): {}".format(e))

    # atualiza o mtime do lock a cada ciclo p/ provar que esta vivo
    def _tocar_lock():
        try:
            with open(lock, "a", encoding="utf-8"):
                os.utime(lock, None)
        except Exception:
            pass

    log.info("=" * 60)
    log.info("ROBO INFINITO iniciado | modelo={} | ciclo={}s | PID={}".format(
        MODELO, INTERVALO, os.getpid()))
    log.info("=" * 60)

    # aquecimento em background: nao atrasa o primeiro ciclo
    def _aquecer():
        teste = pensar("Responda apenas: OK")
        log.info("Ollama: {}".format("conectado" if teste else "INDISPONIVEL (seguindo sem IA)"))

    threading.Thread(target=_aquecer, daemon=True).start()

    while True:
        inicio = time.time()
        try:
            _tocar_lock()
            ciclo()
        except Exception as e:
            # NUNCA morrer: erro no ciclo nao encerra o robo
            log.error("excecao no ciclo (continuando): {}".format(e))
        decorrido = time.time() - inicio
        descanso = max(5, INTERVALO - decorrido)
        time.sleep(descanso)


if __name__ == "__main__":
    main()
