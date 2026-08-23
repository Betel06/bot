# ESPECIFICACAO — TRADER B3 (bot de mini dolar WDO)
> Criada em 22/08/2026. Fase 0 (papel). Reutiliza o esqueleto do bot-futuro
> (`futuro/monitor_futuro.py` + `core/ai_brain.py`) com adaptacoes de mercado.
> Conhecimento base: docs/smc_knowledge.md (projeto local do opencode).

## 1. OBJETIVO

Terceiro servico no Render ("TRADER B3", amarelo 🟡): analise SMC via IA 24/7 em
mini dolar (WDO), paper trading com banco fake de **R$500**, sinal/resultados no
Telegram igual aos outros dois bots. Dinheiro real SÓ depois dos criterios da
Fase 3 batidos.

## 2. CONTRATO (numeros reais)

| Item | WDO | WIN (fallback) |
|---|---|---|
| Valor do ponto | R$10,00 | R$0,20 |
| Tick minimo | 0,5 pt = R$5 | 5 pts = R$1 |
| Sessao | ~09h00–18h25 BRT | idem |
| Vencimento | mensal (F,G,H,J,K,M,N,Q,U,V,X,Z) | bimestral |
| Margem day trade (ordem de grandeza) | R$170–400 | R$100–200 |
| Emolumentos B3 | ~R$0,25–0,50 por contrato por perna | idem |

Corretagem zero nas principais corretoras p/ mini contratos. Day trade: 20% de
imposto sobre ganho liquido mensal (DARF, recolhe o proprio usuario).

## 3. ARQUITETURA (mapeamento do esqueleto)

```
b3/
  config.py          -> ATIVO, JANELAS_SESSAO, ENTRADA_REAIS=500, MAX_SINAIS_DIA,
                        STOP_DIARIO_R=3, TICK/VALOR_PONTO, MERCADO="b3"
  monitor_b3.py      -> copia estrutural de futuro/monitor_futuro.py:
                        Flask + thread monitor + keep-alive interno + /health /status /debug /audit
  telegram.py        -> formatar_sinal/formatar_resultado com branding TRADER B3 🟡
core/
  dados_b3.py        -> NOVO: candles B3 via tvdatafeed (TradingView), simbolo
                        "BMFBOVESPA:WDO1!" (continuo). Mesmo contrato de saida de
                        core/dados.py (DataFrame COLUNAS_PADRAO).
  ai_brain.py        -> reuso integral: TFS_POR_MERCADO["b3"], PROMPT_B3,
                        _arquivo_log("b3") -> logs/ai_decisions_b3.jsonl
```

- **Dados**: tvdatafeed (pip install git+https://github.com/rongardF/tvdatafeed),
  HTTP puro roda no Linux do Render. Anonimo: barras limitadas; com conta gratis
  TradingView: ate 5000 barras/request (env TV_USER/TV_PASS opcionais).
  Fallback se TV cair: USDBRL=X do Yahoo como proxy SOMENTE pra monitor (nunca sinal).
- **IA**: mesma cadeia Gemini com fallback (AI_MODELS), mesmo _validar com R:R>=1.5,
  mesma auditoria jsonl. Cota: 1 ativo so, rodada a cada 5min dentro da sessao =
  ~110 chamadas/dia maximo (janelas) — dentro da gratuidade combinada.
- **Persistencia**: core/persist.py com secao "b3" no estado.json do GitHub
  (logs/b3_posicoes.json, b3_resultados.json). Sobrevive a restart como os outros.

## 4. SESSAO E KILLZONES (America/Sao_Paulo; Render roda UTC)

| Janela | Horario BRT | Racional |
|---|---|---|
| Abertura Brasil | 09h00–10h30 | PO3: manipulacao do range noturno, sweep de abertura |
| Abertura NY | 10h30–12h30 | maior volume do dia, melhor janela SMC |
| Tarde | 15h00–17h00 | fluxo gringo pos-almoço; PTAX/fixing |
| Fora | resto | SEM sinal (ver STUDY_MODE abaixo) |

- Rodadas de analise so disparam dentro de janela (checagem por timezone
  America/Sao_Paulo, nunca hora do server).
- **STUDY_MODE** (env B3_STUDY_MODE=1, default on): fora da sessao, a cada 30min a
  IA analisa DXY (TVC:DXY) e registra decisao em ai_decisions_b3.jsonl com flag
  "estudo", sem gerar sinal — mantem o "24/7 analisando" sem queimar sinal ruim.

## 5. FILTRO DE NOTICIAS (obrigatorio no WDO)

Blackout simples v1: env B3_BLACKOUT="SEG 09:00-09:30,QUA 09:00-09:30" + datas de
evento manual (COPOM/Focus/payroll/Fed) num JSON versionado (docs/calendario_b3.json).
Dentro de blackout: nenhuma entrada; posicao aberta segue gestao normal.
Fase 2: integrar calendario economico automatico (API gratuita).

## 6. GESTAO DE RISCO PAPER (banco R$500)

- Entrada fixa: 1 contrato. Sem piramide na fase papel.
- Risco por trade alvo: 2% = R$10. REGRA DE OURO: stop vem da ESTRUTURA (smc:
  alem do low/high do sweep/OB); se risco estrutural > R$25 (5%), setup e
  DESCARTADO e isso fica logado — e o dado que vai provar quando precisamos de
  mais capital pra operar WDO real.
- Stop diario: 3R (R$50 = 10% do banco). Atingiu: bot para o dia (sem novos sinais,
  resultados seguem sendo checados).
- Max 3 sinais/dia (seletividade Azvdou). Meta diaria atingida (+2R): para tambem.
- Fechamento forcado: posicao aberta as 17h45 encerra no preco corrente (day trade!).
- Lucro em reais = pontos * VALOR_PONTO * contratos - custos (~R$1 round trip).

## 7. ADAPTACAO DO PROMPT DA IA

PROMPT_B3 (novo bloco, mesmo padrao do PROMPT_FUTUROS):
- Contexto: futuros B3, day trade, LONG e SHORT naturais, tick 0,5pt=R$5.
- Sessao atual injetada no prompt ("JANELA: ABERTURA NY").
- Referencias de liquidez proprias: high/low do dia anterior, gap de abertura,
  PTAX, topo/fundo da madrugada (overnight range).
- Alerta explicito: eventos macro (COPOM/Fed) invalidam leitura puramente tecnica;
  se blackout ou evento < 30min, resposta correta e NADA.
- TFS: (("60m",40),("15m",50),("5m",60)) — tvdatafeed usa "60"/"15"/"5".

## 8. ENDPOINTS E TELEGRAM

- Identicos ao futuro: /health, /status (bloco b3/monitor + banco fake), /debug
  (thread_viva + logs memoria), /audit (ultimas decisoes IA).
- Telegram: mesmos TELEGRAM_TOKEN/CHAT_ID. Mensagens "🟡 TRADER B3". Painel
  combinado (tabela fixa) ganha 3a coluna na Fase 2 — exige update do parser
  (core/tg_history.py aceitar linha TRADER B3) — tarefa separada, nao bloqueia.

## 9. RENDER (deploy)

- Novo servico web "bot-b3": mesmo repo Betel06/bot, startCommand
  `python b3/monitor_b3.py`. Env vars: AI_ENABLED=1, GEMINI_API_KEY,
  AI_INTERVALO=300, B3_STUDY_MODE=1, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
  SPOT_BANCO... nao se aplica — B3_BANCO_INICIAL=500.
- Lembrancas das licoes: env var setada apos criacao exige redeploy; conferir
  /debug apos deploy; testar local antes com as mesmas env vars.
- Keep-alive: thread interna de 10min (igual aos outros) basta.

## 10. ROADMAP

- **Fase 0 (esta spec)**: aprovar documento.
- **Fase 1 — backtest (ANTES de codar o bot)**: script `backtest_wdo.py` baixa
  5000 barras 5m/15m do WDO1!, aplica as regras objetivas do smc_knowledge.md
  secao 11 (sweep/OB+CHoCH/discount/premium, R:R>=1.5, killzone), mede win rate,
  payoff, expectativa e distribuicao por dia da semana. Criterio de seguir:
  expectativa positiva em 6 meses simulados com custo R$1/trade embutido.
- **Fase 2 — paper 24/7**: implementar b3/ conforme spec, deploy, acumular 2-3
  semanas de sinais auditados (mesmo metodo do experimento atual dos outros bots).
- **Fase 3 — real (so com criterios batidos)**: conta real com R$500 em 1 WIN ou
  WDO conforme margem da corretora, execucao MANUAL pelo usuario no inicio
  (bot manda sinal, humano executa) — depois evolui pra MT5/ProfitDLL num Windows
  local agindo como executor, com o Render mantendo o cerebro.

## 11. RISCOS CONHECIDOS

- tvdatafeed e API nao oficial: pode quebrar com mudanca do TradingView ->
  mitigacao: fallback proxy + alarme no /status se fonte falhar N rodadas.
- Contrato continuo vs especifico: WDO1! serve pra ANALISE; execucao real usara
  contrato do mes (ex: WDOU26) — diferenca pequena, mas anotar no log qual serie.
- Quota Gemini compartilhada com o futuro: cadeia de fallback ja cobre; monitorar
  429 no /debug.
- Feriados B3 (sessoes sem mercado): calendario B3 hardcoded v1 (lista anual),
  loop apenas dorme.
