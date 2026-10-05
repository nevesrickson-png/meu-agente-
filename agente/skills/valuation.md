# Skill: valuation de empresas (USO INTERNO)

**Quando usar:** "quanto vale a WEG", DCF, múltiplos, tese de investimento, setor, resultado trimestral, `/empresa`,
`/valuation`, `/tese`, `/setor`, `/resultado`.

## Compliance (obrigatório)
- Relatório de análise para terceiros é exclusivo de analista CNPI (Resolução CVM 20). Tudo aqui é **uso interno e de
  estudo**: nunca escreva texto de recomendação para cliente a partir destes relatórios. O rodapé "Uso interno — não
  constitui relatório de análise" vai sempre.

## Dados e ferramentas
- Ticker com `quiron_mercado__buscar_empresa`. Demonstrações da **CVM** (DFP/ITR padronizados), cotação brapi/Yahoo,
  custo de capital com Treasury (^TNX), Damodaran (ERP, risco-país, β por setor) e Focus (IPCA longo).
- `analisar("valuation_dcf", {"empresa": "WEGE3", "tese": "...opcional..."})` — raio-X, WACC, DCF de 10 anos, cenários,
  sensibilidade, DCF reverso e pontos de debate. Ajustes opcionais: `crescimento_inicial`, `margem_ebit`,
  `setor_damodaran`.
- `setor_multiplos {"empresa", "pares": [...]}` · `resultado_trimestral {"empresa"}`.
- Bancos e seguradoras: o DCF da firma não se aplica — use `setor_multiplos` (P/L, P/VP, ROE).

## Como discutir (CFA/CNPI)
- **Debate de tese** (`/tese`): use o modo debater ou contestar. Comece pelo DCF reverso — o que o preço exige
  (crescimento e custo de capital implícitos) — e confronte com o histórico (CAGR, margens, ROIC).
- Diga as duas visões de risco: β de setor (Damodaran) × β de regressão, e quanto o valor muda.
- Peso da perpetuidade alto = conclusão frágil. Itens não recorrentes não são ajustados: aponte quando a margem do
  ano destoar.
- Nunca invente números: se faltar dado, diga o que falta.
