# Huntera Game Configuration
# Configurações do bot de jogo Huntera (MMORPG de caça)

# === BÁSICO ===
# Entrada em moeda do jogo (padrão: 1000 GP - Gold Points)
HUNTERA_ENTRADA_GP = int(os.environ.get("HUNTERA_ENTRADA_GP", "1000"))

# Banco inicial de GP no jogo
HUNTERA_BANCO_INICIAL = int(os.environ.get("HUNTERA_BANCO_INICIAL", "5000"))

# Intervalo de rodadas em segundos (padrão: 8s para jogo rodar fluido)
INTERVALO_RODADA = int(os.environ.get("HUNTERA_INTERVALO", "8"))

# Nome do personagem
HUNTERA_PERSONAGEM = os.environ.get("HUNTERA_PERSONAGEM", "MinhaCaça")

# Servidor do jogo
HUNTERA_SERVIDOR = os.environ.get("HUNTERA_SERVIDOR", "br1")

# Modo: "caça", "pesca", "quests" - qual atividade focar
HUNTERA_MODO = os.environ.get("HUNTERA_MODO", "caça").lower()

# Quantidade máxima de rodadas por sessão (0 = ilimitado)
MAX_RODADAS_SESSAO = int(os.environ.get("HUNTERA_MAX_RODADAS", "0"))

# === SISTEMA DE INVENTÁRIO / BOLSA ===
# Slots totais da bolsa do personagem
HUNTERA_BOLSA_SLOTES = int(os.environ.get("HUNTERA_BOLSA_SLOTES", "20"))

# Quantidade de itens por tipo antes de considerar "cheia"
HUNTERA_ITEMS_POR_TIPO_LIMITE = int(os.environ.get("HUNTERA_ITEMS_POR_TIPO_LIMITE", "10"))

# === SISTEMA DE 9 LUGARES DE CAÇA ===
# Formato: "nome_local": {"area": "descricao", "animal": "tipo", "risco": 1-5, "melhor_horario": "hh:mm"}
HUNTERA_LUGARES_CACA = {

    "L1_Nova_Reserva": {
        "area": "Reserva Principiante - Área segura",
        "animal": "Coelho, Veado pequeno",
        "risco": 1,
        "melhor_horario": "00:00-12:00",
        "ativo": True
    },

    "L2_Vale_Dourado": {
        "area": "Vale Dourado - Recursos médios",
        "animal": "Veado médio, Jabuti",
        "risco": 2,
        "melhor_horario": "06:00-18:00",
        "ativo": True
    },

    "L3_Selva_Profundidade": {
        "area": "Selva Profunda - Rico em troféus",
        "animal": "Tapir, Onça-parda",
        "risco": 3,
        "melhor_horario": "12:00-20:00",
        "ativo": True
    },

    "L4_Pantanal_Brasileiro": {
        "area": "Pantanal - Alta reprodução",
        "animal": "Cervo-açu, Capivara",
        "risco": 2,
        "melhor_horario": "18:00-23:59",
        "ativo": True
    },

    "L5_Montanhas_Geladas": {
        "area": "Montanhas - Troféus raros",
        "animal": "Veado-da-catingueira, Urso",
        "risco": 3,
        "melhor_horario": "20:00-04:00",
        "ativo": True
    },

    "L6_Floresta_Nebulosa": {
        "area": "Floresta Nebulosa - Experiência alta",
        "animal": "Lobo, Ura",
        "risco": 2,
        "melhor_horario": "02:00-10:00",
        "ativo": True
    },

    "L7_Praia_Sudoeste": {
        "area": "Praia - Pesca e caça costeira",
        "animal": "Peixe-gigante, Gaivotão",
        "risco": 1,
        "melhor_horario": "10:00-16:00",
        "ativo": True
    },

    "L8_Cavernas_Profundas": {
        "area": "Cavernas - Subchefes e itens únicos",
        "animal": "Morcego gigante, Esqueleto",
        "risco": 4,
        "melhor_horario": "00:00-06:00",
        "ativo": True
    },

    "L9_Pico_Summit": {
        "area": "Pico Summit - Máximo risco/retorno",
        "animal": "Veão alpino, Águia-real",
        "risco": 5,
        "melhor_horario": "06:00-12:00",
        "ativo": True
    },
}

# Horário atual do servidor (será atualizado pelo bot)
HUNTERA_HORARIO_SERVIDOR = datetime.now().strftime("%H:%M")

# Sistema de seleção: quale lugar está melhor agora
HUNTERA_SYSTEM_SELECAO_AUTO = os.environ.get("HUNTERA_SYSTEM_SELECAO_AUTO", "True").lower() in ("true", "1", "yes")

# Se True, rota automaticamente. Se False, fica no último lugar escolhido
HUNTERA_LIMITE_RISCO = int(os.environ.get("HUNTERA_LIMITE_RISCO", "3"))

# === SISTEMA DE RETORNO À CIDADE / VENDA ===
# Coordenadas ou área da "cidade" / banco / loja no jogo
# Estes valores dependem do mapa do Huntera - ajustar conforme o jogo
HUNTERA_CIDADE_AREA = {
    "nome": "Cidade Principal",
    "x_min": 0,
    "x_max": 0,
    "y_min": 0,
    "y_max": 0,
    "ativo": True  # Se True, bot vai à cidade quando bolsa cheia
}

# Quantidade de GP para "pagar taxa" da cidade (se houver taxa)
HUNTERA_TAXA_CIDADE_GP = int(os.environ.get("HUNTERA_TAXA_CIDADE_GP", "0"))

# Quantidade máxima de itens a vender por visita à cidade
HUNTERA_ITENS_VENDER_MAX = int(os.environ.get("HUNTERA_ITENS_VENDER_MAX", "20"))

# Tempo em segundos para "simular" a venda na cidade
HUNTERA_TEMPO_VENDA = int(os.environ.get("HUNTERA_TEMPO_VENDA", "3"))

# Se True, o bot salva o progresso do último lugar antes de ir à cidade
HUNTERA_SALVAR_PROGRESSO = os.environ.get("HUNTERA_SALVAR_PROGRESSO", "True").lower() in ("true", "1", "yes")