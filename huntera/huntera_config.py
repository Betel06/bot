# Huntera Game Configuration

import os

# === CAPACIDADE / BOLSA ===
# Limite de oz antes de ir a cidade vender (alerta)
CAPACIDADE_MAX = 1500.0

# Peso para dispatch preventivo
PESO_ALERTA = 1000.0

# Peso considerado "cheio" - precisa dispatch
PESO_CHEIO = 1400.0

# === CAÇADAS DO JOGO (reais, baseado no Huntera) ===
# Formato: {"nome": {"level_min": X, "risco": 1-5, "tipo": "pvp/pve"}}
CAÇAS = {
    "Grimvale Warrens": {
        "level_min": 20,
        "risco": 2,
        "tipo": "pve",
        "descricao": "Tuneis dos werebadgers - niveis baixos"
    },
    "Grimvale Dens": {
        "level_min": 30,
        "risco": 3,
        "tipo": "pve",
        "descricao": "Wereboars e werebears - niveis medios"
    },
    "Yalahar": {
        "level_min": 50,
        "risco": 3,
        "tipo": "pve",
        "descricao": "Cacadas novas em Yalahar"
    },
    "Venore": {
        "level_min": 30,
        "risco": 2,
        "tipo": "pve",
        "descricao": "Rotworms e crabs"
    },
    "Darama": {
        "level_min": 20,
        "risco": 2,
        "tipo": "pve",
        "descricao": "Lions e dragons spawn"
    },
    "Carlin": {
        "level_min": 15,
        "risco": 1,
        "tipo": "pve",
        "descricao": "Saga corrompida e amazonas"
    },
    "Thais": {
        "level_min": 10,
        "risco": 1,
        "tipo": "pve",
        "descricao": "Dragons e missionaries"
    },
    "Svargrond": {
        "level_min": 40,
        "risco": 3,
        "tipo": "pve",
        "descricao": "Ice raiders e berserkers"
    },
    "Ab'Dendriel": {
        "level_min": 25,
        "risco": 2,
        "tipo": "pve",
        "descricao": "Elfs e warlocks"
    },
    "Dragon Lair": {
        "level_min": 55,
        "risco": 5,
        "tipo": "pve",
        "descricao": "Dragons - nivel alto (Ousado)"
    },
}

# === HUNT FIXA / TIER (forcar uma caçada especifica) ===
# Se CACADA_FIXA nao for vazio, o bot SEMPRE vai pra essa caçada (ignora _melhor_cacada).
# TIER_CACADA: "Cauteloso" | "Ousado" | "Agressivo"
CACADA_FIXA = os.environ.get("HUNTERA_CACADA_FIXA", "Dragon Lair")
TIER_CACADA = os.environ.get("HUNTERA_TIER", "Ousado")

# === HORARIOS DE CAÇA (killzones) ===
# Horarios em que o bot deve focar em caçar
HORARIOS_CACA = {
    "manha": {"inicio": "06:00", "fim": "12:00"},
    "tarde": {"inicio": "12:00", "fim": "18:00"},
    "noite": {"inicio": "18:00", "fim": "00:00"},
    "madrugada": {"inicio": "00:00", "fim": "06:00"},
}

# === POCOES ===
# Teclas do teclado para pocoes
POCAO_HP_TECLA = "1"
POCAO_MP_TECLA = "2"

# Percentual minimo para usar pocao
POCAO_HP_LIMITE = 70  # Usa pocao se HP < 70%
POCAO_MP_LIMITE = 50  # Usa pocao se MP < 50%

# === DISPATCH ===
# Dispatch a cada X horas (gratuito = 1h, premium = 30min)
DISPATCH_INTERVALO_SEGUNDOS = 1800

# Dispatch preventivo quando capacity > X% do maximo (90% = mochila quase cheia)
DISPATCH_LIMITE_PCT = 90

# === ROTACAO DE CACADAS ===
# Troca de caçada a cada X ciclos
ROTACAO_CACADA_CICLOS = 300

# === MONITORAMENTO ===
# Intervalo de log detalhado (ciclos)
LOG_INTERVALO_CICLOS = 10

# === TELEGRAM ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_NOTIF_INTERVALO = 1800  # 30 minutos em segundos
