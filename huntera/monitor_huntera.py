import sys
import os
import json
import time
import random
import threading
import logging
import subprocess
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, jsonify

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

import collections

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

for _h in logging.getLogger().handlers:
    _h.formatter.converter = lambda *a: datetime.now(timezone.utc).timetuple()


class _FiltroHealth(logging.Filter):
    def filter(self, record):
        return "/health" not in record.getMessage()


logging.getLogger("werkzeug").addFilter(_FiltroHealth())

LOG_BUFFER = collections.deque(maxlen=200)


class _BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            LOG_BUFFER.append(self.format(record))
        except Exception:
            pass


_bufh = _BufferHandler()
_bufh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_bufh)

from huntera_config import (
    HUNTERA_ENTRADA_GP,
    HUNTERA_BANCO_INICIAL,
    INTERVALO_RODADA,
    HUNTERA_PERSONAGEM,
    HUNTERA_SERVIDOR,
    HUNTERA_MODO,
    MAX_RODADAS_SESSAO,
    HUNTERA_LUGARES_CACA,
    HUNTERA_HORARIO_SERVIDOR,
    HUNTERA_SYSTEM_SELECAO_AUTO,
    HUNTERA_LIMITE_RISCO,
    HUNTERA_BOLSA_SLOTES,
    HUNTERA_ITEMS_POR_TIPO_LIMITE,
    HUNTERA_CIDADE_AREA,
    HUNTERA_TAXA_CIDADE_GP,
    HUNTERA_ITENS_VENDER_MAX,
    HUNTERA_TEMPO_VENDA,
    HUNTERA_SALVAR_PROGRESSO,
)

POSICOES_FILE = os.path.join(BOT_DIR, "logs", "posicoes_huntera.json")
RESULTADOS_FILE = os.path.join(BOT_DIR, "logs", "resultados_huntera.json")
TABELA_FILE = os.path.join(BOT_DIR, "logs", "tabela_msg_huntera.json")

ESTADO = {
    "modo": HUNTERA_MODO,
    "personagem": HUNTERA_PERSONAGEM,
    "servidor": HUNTERA_SERVIDOR,
    "ultima_rodada": None,
    "rodada": 0,
    "total_rodadas": 0,
    "trofeus_coletados": 0,
    "pesos_pegos": 0,
    "lugar_atual": "nenhum",
    "mudanca_lugar_rodada": 0,
    "tempo_no_lugar": 0,
    "bolsa_slots_ocupados": 0,
    "itens_na_bolsa": 0,
    "seguranca_ativo": True,
    "indo_cidade": False,
    "ultima_volta_cidade": 0,
    "ultimo_lugar_farm": "nenhum",
}

bot_process = None


def get_servidor_horario():
    """Pega horário do servidor - simplificado, usa hora local do bot."""
    return datetime.now().strftime("%H:%M")


def selecionar_lugar_caca():
    """Seleciona automaticamente o melhor lugar de caça baseado no horário e risco."""
    horario_atual = get_servidor_horario()
    HUNTERA_HORARIO_SERVIDOR = horario_atual

    # Filtra apenas lugares ativos
    lugares_ativos = {k: v for k, v in HUNTERA_LUGARES_CACA.items() if v.get("ativo", True)}

    # Classifica por melhor horário e risco
    candidatos = []
    for nome, dados in lugares_ativos.items():
        melhor_horario = dados.get("melhor_horario", "00:00-23:59")
        risco = dados.get("risco", 99)

        try:
            # Parse do melhor horário (formato "hh:mm-hh:mm")
            inicio, fim = melhor_horario.split("-")
            inicio_h, inicio_m = map(int, inicio.split(":"))
            fim_h, fim_m = map(int, fim.split(":"))

            # Verifica se horário atual está no intervalo
            atual_h, atual_m = map(int, horario_atual.split(":"))
            atual_minutos = atual_h * 60 + atual_m
            inicio_minutos = inicio_h * 60 + inicio_m
            fim_minutos = fim_h * 60 + fim_m

            # Handle crossing midnight
            if inicio_minutos <= fim_minutos:
                horario_ok = inicio_minutos <= atual_minutos <= fim_minutos
            else:
                # Cruzou a meia-noite (ex: 22:00-06:00)
                horario_ok = atual_minutos >= inicio_minutos or atual_minutos <= fim_minutos

            # Bônus se está no horário certo
            bonus_horario = 0 if horario_ok else -1

            # Risco menor = melhor para segurança (invertido para ordenação)
            risco_penalty = risco * 0.5

            # Score final: horário certo + risco baixo
            score = bonus_horario * 2 + (5 - risco) + bonus_horario
            candidatos.append((score, nome, dados))
        except Exception as e:
            logging.warning("[SELECT] Erro ao parsear horário de {}: {}".format(nome, e))
            risco = dados.get("risco", 99)
            candidatos.append((5 - risco, nome, dados))

    # Ordena pelo score (maior = melhor)
    candidatos.sort(key=lambda x: x[0], reverse=True)

    # Retorna o melhor lugar, respeitando limete de risco
    for score, nome, dados in candidatos:
        risco = dados.get("risco", 99)
        if risco <= HUNTERA_LIMITE_RISCO or not HUNTERA_SYSTEM_SELECAO_AUTO:
            logging.info("[SELECT] Selecionado lugar: {} (score: {}, risco: {})".format(nome, score, risco))
            return nome, dados

    # Se nenhum lugar passou no limite de risco, retorna o de menor risco
    logging.warning("[SELECT] Nenhum lugar dentro do limite de risco {}".format(HUNTERA_LIMITE_RISCO))
    melhor = candidatos[-1] if candidatos else (0, "L1_Nova_Reserva", HUNTERA_LUGARES_CACA.get("L1_Nova_Reserva", {}))
    return melhor[1], melhor[2]


def verificar_seguranca_lugar(lugar_dados):
    """Verifica se é seguro ficar naquele lugar baseado no risco e tempo."""
    risco = lugar_dados.get("risco", 99)
    if risco > HUNTERA_LIMITE_RISCO:
        logging.warning("[SEGURANCA] Risco {} acima do limite {} - ativando rota preventiva".format(risco, HUNTERA_LIMITE_RISCO))
        return False
    return True


def verificar_bolsa_cheia():
    """Verifica se a bolsa está cheia baseada na configuração."""
    slots_ocupados = ESTADO.get("bolsa_slots_ocupados", 0)
    limite_slots = HUNTERA_BOLSA_SLOTES

    # Também verifica por tipo de item
    items_tipo = ESTADO.get("itens_na_bolsa", 0)
    limite_tipo = HUNTERA_ITEMS_POR_TIPO_LIMITE

    bolsa_cheia_por_slots = slots_ocupados >= limite_slots
    bolsa_cheia_por_tipo = items_tipo >= limite_tipo

    return bolsa_cheia_por_slots or bolsa_cheia_por_tipo


def ir_cidade_vender():
    """Função que executa a lógica de ir à cidade, vender itens e voltar."""
    global ESTADO

    if ESTADO["indo_cidade"]:
        return  # Já está indo ou na cidade

    ESTADO["indo_cidade"] = True
    ESTADO["ultima_volta_cidade"] = time.time()
    ESTADO["mudanca_lugar_rodada"] = ESTADO["rodada"]

    horario_atual = get_servidor_horario()
    logging.info("[CIDADE] Bolsa cheia! Indo à cidade vender itens... (Horário: {})".format(horario_atual))

    try:
        # 1. Log da situação atual
        logging.info("[CIDADE] Bolsa: {} / {} slots ocupados".format(
            ESTADO.get("bolsa_slots_ocupados", 0), HUNTERA_BOLSA_SLOTES))
        logging.info("[CIDADE] Itens por tipo: {} / {}".format(
            ESTADO.get("itens_na_bolsa", 0), HUNTERA_ITEMS_POR_TIPO_LIMITE))

        # 2. Simular tempo de venda
        tempo_venda = HUNTERA_TEMPO_VENDA
        logging.info("[CIDADE] Vendendo itens por {} segundos...".format(tempo_venda))
        time.sleep(tempo_venda)

        # 3. Registrar lucro com a venda
        # Simular: ao vender, recupera parte do valor da entrada
        lucro_venda = int(HUNTERA_ENTRADA_GP * 0.3)  # 30% do valor da entrada como "lucro" da venda
        ESTADO["trofeus_coletados"] = ESTADO.get("trofeus_coletados", 0) + lucro_venda

        # 4. Limpar/contar itens vendidos
        ESTADO["bolsa_slots_ocupados"] = 0
        ESTADO["itens_na_bolsa"] = 0

        # 5. Salvar progresso antes de voltar
        if HUNTERA_SALVAR_PROGRESSO:
            ESTADO["ultimo_lugar_farm"] = ESTADO["lugar_atual"]
            logging.info("[CIDADE] Progresso salvo no lugar: {}".format(ESTADO["ultimo_lugar_farm"]))

        logging.info("[CIDADE] Venda concluída! {} GP adicionados. Bolso agora tem {} slots.".format(
            lucro_venda, HUNTERA_BOLSA_SLOTES - ESTADO["bolsa_slots_ocupados"]))

    except Exception as e:
        logging.error("[CIDADE] Erro ao vender: {}".format(e))

    finally:
        # 6. Voltar ao lugar de farm
        ESTADO["indo_cidade"] = False
        logging.info("[CIDADE] Voltando ao lugar de farm após venda.")

        # Não selecionar novo lugar imediatamente - continuar no mesmo lugar
        # O sistema de rota fará a mudança nas próximas rodadas


def monitor_loop():
    """Loop principal do bot Huntera com farm completo e retorno à cidade."""
    time.sleep(10)

    global ESTADO

    # Atualiza horário do servidor
    horario_atual = get_servidor_horario()
    HUNTERA_HORARIO_SERVIDOR = horario_atual

    # Se sistema de seleção automática, escolhe lugar
    if HUNTERA_SYSTEM_SELECAO_AUTO:
        lugar_nome, lugar_dados = selecionar_lugar_caca()
        ESTADO["lugar_atual"] = lugar_nome
        ESTADO["tempo_no_lugar"] = 0
        ESTADO["ultimo_lugar_farm"] = lugar_nome
        logging.info("[SYSTEM] Lugar de caça selecionado: {} - {}".format(lugar_nome, lugar_dados.get("area", "N/A")))

    # Mensagem de início no Telegram
    enviar_mensagem("🟢 Bot Huntera iniciado!\nLugar: {}\nModo: {}\nNotificações: a cada 30min".format(
        ESTADO["lugar_atual"], HUNTERA_MODO))
    else:
        # Fica no lugar fixo configurado ou no último
        lugar_fixo = os.environ.get("HUNTERA_LUGAR_FIXO", "L1_Nova_Reserva")
        lugar_dados = HUNTERA_LUGARES_CACA.get(lugar_fixo, HUNTERA_LUGARES_CACA.get("L1_Nova_Reserva", {}))
        ESTADO["lugar_atual"] = lugar_fixo
        if lugar_dados:
            ESTADO["tempo_no_lugar"] = 0

    # Se segurança ativa, verifica risco
    if ESTADO["seguranca_ativo"]:
        seguro = verificar_seguranca_lugar(lugar_dados)
        if not seguro:
            logging.info("[SEGURANCA] Mudando para lugar mais seguro...")
            if HUNTERA_SYSTEM_SELECAO_AUTO:
                lugar_nome, lugar_dados = selecionar_lugar_caca()
                ESTADO["lugar_atual"] = lugar_nome
                ESTADO["tempo_no_lugar"] = 0

    rodada = 0
    intervalo = INTERVALO_RODADA

    while True:
        rodada += 1
        agora = datetime.now()

        try:
            # Garante que bot está rodando (Playwright/Node)
            if bot_process is None or bot_process.poll() is not None:
                logging.info("[HUNTERA] Verificando status do bot de jogo...")

            # Verificar se bolsa está cheia A CADA RODADA
            if verificar_bolsa_cheia():
                logging.info("[ITEM] Bolsa cheia detectada! (Slots: {}/{} itens: {})".format(
                    ESTADO.get("bolsa_slots_ocupados", 0), HUNTERA_BOLSA_SLOTES,
                    ESTADO.get("itens_na_bolsa", 0)))
                ir_cidade_vender()

            # Atualiza tempo no lugar atual
            ESTADO["tempo_no_lugar"] += intervalo
            ESTADO["rodada"] = rodada
            ESTADO["total_rodadas"] += 1

            # Simula progresso do jogo (troféus, peso, itens na bolsa)
            ganho_trofeu = random.randint(0, 3)
            ganho_peso = random.randint(0, 5)
            ganho_item = random.randint(0, 2)
            ESTADO["trofeus_coletados"] += ganho_trofeu
            ESTADO["pesos_pegos"] += ganho_peso
            ESTADO["bolsa_slots_ocupados"] = min(
                ESTADO.get("bolsa_slots_ocupados", 0) + ganho_item,
                HUNTERA_BOLSA_SLOTES
            )
            ESTADO["itens_na_bolsa"] = ESTADO["bolsa_slots_ocupados"]

            # A cada X rodadas ou Y minutos, muda de lugar para evitar monotonia
            # e para evitar que a bolsa encher muito rápido em um só lugar
            if rodada % 20 == 0 or ESTADO["tempo_no_lugar"] > 300:
                logging.info("[ROTA] Mudando de lugar após {} rodadas/tempo".format(rodada))
                if HUNTERA_SYSTEM_SELECAO_AUTO:
                    lugar_nome, lugar_dados = selecionar_lugar_caca()
                    ESTADO["lugar_atual"] = lugar_nome
                    ESTADO["tempo_no_lugar"] = 0
                    ESTADO["mudanca_lugar_rodada"] = rodada
                    ESTADO["ultimo_lugar_farm"] = lugar_nome
                    logging.info("[ROTA] Novo lugar: {} - {}".format(lugar_nome, lugar_dados.get("area", "N/A")))

            # Log de status a cada 10 rodadas
            if rodada % 10 == 0:
                logging.info(
                    "[HUNTERA] Rodada {} | Lugar: {} | Bolsa: {}/{} slots | Troféus: {} | Peso: {} | Risco: {} | Cidade: {}".format(
                        rodada,
                        ESTADO["lugar_atual"],
                        ESTADO.get("bolsa_slots_ocupados", 0), HUNTERA_BOLSA_SLOTES,
                        ESTADO["trofeus_coletados"],
                        ESTADO["pesos_pegos"],
                        HUNTERA_LUGARES_CACA.get(ESTADO["lugar_atual"], {}).get("risco", "N/A"),
                        "SIM" if ESTADO["indo_cidade"] else "NÃO"
                    )
                )

            # Salva estado periodicamente
            salvar_posicoes([])
            salvar_resultados({
                "total_rodadas": ESTADO["total_rodadas"],
                "trofeus_coletados": ESTADO["trofeus_coletados"],
                "pesos_pegos": ESTADO["pesos_pegos"],
                "lugar_atual": ESTADO["lugar_atual"],
                "indo_cidade": ESTADO["indo_cidade"],
            })

            # Envia update no Telegram a cada 30 min (~225 rodadas)
            if rodada % 225 == 0:
                try:
                    msg = "🟢 Huntera 30min | Rodadas: {} | Lugar: {} | Troféus: {} | Peso: {}g | Bolsa: {}/{}".format(
                        ESTADO["total_rodadas"], ESTADO["lugar_atual"],
                        ESTADO["trofeus_coletados"], ESTADO["pesos_pegos"],
                        ESTADO.get("bolsa_slots_ocupados", 0), HUNTERA_BOLSA_SLOTES)
                    enviar_mensagem(msg)
                except Exception as e:
                    logging.error("[TELEGRAM] falha: {}".format(e))

            logging.info(
                "[Rodada {}] Lugar: {} | Bolsa: {}/{} | Troféus: {} | Peso: {} | Tempo: {}s".format(
                    rodada, ESTADO["lugar_atual"], ESTADO.get("bolsa_slots_ocupados", 0), HUNTERA_BOLSA_SLOTES,
                    ESTADO["trofeus_coletados"], ESTADO["pesos_pegos"], ESTADO["tempo_no_lugar"]
                ))

        except Exception as e:
            logging.error("[ERRO] {}".format(e))

        time.sleep(intervalo)


def keep_alive_loop():
    """Loop keep-alive para Render."""
    url = os.environ.get("RENDER_EXTERNAL_URL") or ("http://127.0.0.1:" + os.environ.get("PORT", "5000"))
    while True:
        try:
            requests.get(url.rstrip("/") + "/health", timeout=30)
        except Exception:
            pass
        time.sleep(600)


def salvar_posicoes(data):
    try:
        os.makedirs(os.path.dirname(POSICOES_FILE), exist_ok=True)
        with open(POSICOES_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def salvar_resultados(data):
    try:
        os.makedirs(os.path.dirname(RESULTADOS_FILE), exist_ok=True)
        with open(RESULTADOS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def carregar_resultados():
    try:
        with open(RESULTADOS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "total_rodadas": ESTADO.get("total_rodadas", 0),
            "trofeus_coletados": ESTADO.get("trofeus_coletados", 0),
            "pesos_pegos": ESTADO.get("pesos_pegos", 0),
            "lugar_atual": ESTADO.get("lugar_atual", "nenhum"),
            "indo_cidade": ESTADO.get("indo_cidade", False),
        }


def carregar_config():
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def enviar_mensagem(texto):
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False, ""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": texto}, timeout=10)
        return resp.ok, resp.text
    except Exception as e:
        logging.error("[TELEGRAM] erro ao enviar: {}".format(e))
        return False, ""


app = Flask(__name__)


@app.route("/")
def hello_world():
    r = carregar_resultados()
    return {
        "bot": "huntera",
        "status": "online",
        "modo": ESTADO["modo"],
        "personagem": ESTADO["personagem"],
        "servidor": HUNTERA_SERVIDOR,
        "total_rodadas": r["total_rodadas"],
        "trofeus_coletados": r["trofeus_coletados"],
        "pesos_pegos": r["pesos_pegos"],
        "lugar_atual": ESTADO["lugar_atual"],
        "bolsa_slots": "{} / {}".format(ESTADO.get("bolsa_slots_ocupados", 0), HUNTERA_BOLSA_SLOTES),
    }


@app.route("/health")
def health():
    return "ok"


@app.route("/status")
def status():
    r = carregar_resultados()
    return {
        "bot": "huntera",
        "status": "online",
        "modo": ESTADO["modo"],
        "personagem": ESTADO["personagem"],
        "servidor": HUNTERA_SERVIDOR,
        "total_rodadas": r["total_rodadas"],
        "trofeus_coletados": r["trofeus_coletados"],
        "pesos_pegos": r["pesos_pegos"],
        "lugar_atual": ESTADO["lugar_atual"],
        "horario_servidor": HUNTERA_HORARIO_SERVIDOR,
        "bolsa_slots": "{} / {}".format(ESTADO.get("bolsa_slots_ocupados", 0), HUNTERA_BOLSA_SLOTES),
        "indo_cidade": ESTADO["indo_cidade"],
    }


@app.route("/lugares")
def listar_lugares():
    return {"bot": "huntera", "lugares": HUNTERA_LUGARES_CACA}


@app.route("/debug")
def debug():
    try:
        viva = False
        if bot_process is not None:
            viva = bot_process.poll() is None
        return {
            "thread_viva": viva,
            "estado": ESTADO,
            "logs": list(LOG_BUFFER)[-50:],
        }
    except Exception as e:
        return {"erro": str(e)}


MONITOR_THREAD = None


def iniciar_app():
    global MONITOR_THREAD

    MONITOR_THREAD = threading.Thread(target=monitor_loop, daemon=True)
    MONITOR_THREAD.start()

    ping_thread = threading.Thread(target=keep_alive_loop, daemon=True)
    ping_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    iniciar_app()