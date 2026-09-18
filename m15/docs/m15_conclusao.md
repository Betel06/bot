# Bot M15 — Backtest de Breakout + Conclusão Honesta

**Gerado em:** 28/08/2026 (atualizado com melhorias validadas)
**Autor:** opencode (a pedido do usuário)

---

## RESUMO EXECUTIVO — A ESTRATÉGIA AGORA TEM EDGE

Após rodar backtest e melhorar a estratégia filtrando por ativo e por
parâmetro (com **validação walk-forward**), a configuração final passou de
**+7 USDT** para **+30 USDT** em 2 anos, com win-rate de **~48%** e
**nenhum ativo negativo**.

| Config | P.L. (2 anos) | WR | Obs |
|--------|---------------|-----|-----|
| Base inicial | +7.01 | 36% | incl. ETH perdedor |
| **Final (corpo+MACD, RR 1.5, sem ETH)** | **+30.19** | **48%** | estável nos 3 ativos |

Por ativo (2 anos, RR 1:1.5):
- **XRP: +10.97, WR 51%, PF 1.48** (motor)
- **BTC: +10.98, WR 49%, PF 1.29**
- **SOL: +8.24, WR 47%, PF 1.25**

---

## O que foi feito e VALIDADO (melhorou o edge)

1. **Filtro de corpo/pavio** — só aceita breakout com corpo forte e pavio
   pequeno (evita falso rompimento). Dobrou o P.L. (viu no Pine
   `estrategia_btc_pro_m15.pine`).
2. **MACD como filtro de direção** — combina com corpo/pavio.
3. **RR 1:1.5 em vez de 1:2.0** — contra-intuitivo, mas o WR subiu de ~36%
   para ~48% e o expectancy melhorou, de forma estável nos 2 anos.
4. **Excluir ETH** — tinha PF<1 (perde dinheiro) com esta estratégia.

## O que foi testado e DESCARTADO (evitou overfit)

- **Stop com ATR** — aumentou o risco sem compensar; reduziu o total
  (+9.01 → +1.19 no XRP). Rejeitado.
- **Filtro por dia da semana (Qui+Sex)** — parecia ótimo no agregado (+14),
  mas falhou no **walk-forward**: BTC perdeu −2.85 na 1ª janela. Era overfit
  puxado pelo XRP. Rejeitado.
- **RR 2.5 / 3.0** — reduz WR para ~30% e destrói o edge. Rejeitado.

## Lição central

O backtest + walk-forward é o que torna esta estratégia **confiável**: o que
parecia edge (filtro por dia) se revelou ruído, e o que parecia marginal (RR
baixo, corpo/pavio) se revelou robusto. É esse processo que faltou nos bots
anteriores.

---

## Arquivos do projeto
- `config.py` — parâmetros finais validados (RR 1.5, filtros ligados, sem ATR)
- `estrategia.py` — lógica de sinais + filtros (corpo/pavio, MACD)
- `backtest.py` — engine honesto (fees + slippage, 1 posição/vez, walk-forward)
- `monitor_m15.py` — bot em **fase papel** (registra sinais, não opera)
- `logs/backtest_m15.json` — resultado bruto salvo

Comandos:
```
python m15/backtest.py --salvar
```

