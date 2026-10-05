# Skill: carreira (plano, diário de teses, portfólio, entrevista, radar)

**Quando usar:** "como está minha carreira", certificações e datas de prova, "quero registrar uma tese", "revise minhas
teses", portfólio de análises, treino de entrevista, "o que saiu de norma nova", `/carreira`, `/diario`, `/portfolio`,
`/entrevista`, `/radar`.

## Plano → `quiron_carreira__plano_de_carreira`
Mostre o plano e comente como colega sênior: o gargalo do momento (ex.: sem data de prova, track record parado) e 1–3
ações concretas para a semana. Datas de prova com `registrar_prova`; autoavaliação com `avaliar_competencia`.

## Diário de teses → `registrar_tese` / `revisar_teses` / `fechar_tese`
- Registrar: passe o texto **como veio**. Se faltar algo essencial (horizonte, o que invalidaria, confiança), pergunte
  ANTES de registrar — uma tese sem gatilho de invalidação não é falsificável.
- Revisar: use os números da ferramenta (retorno, excesso sobre o Ibovespa) e confronte com as **premissas**, não só
  com o preço (acertar pelo motivo errado também é erro). Modo contestar quando ele pedir advogado do diabo.
- Fechar: peça o aprendizado em 1 frase. Calibração: Brier e faixas de confiança vêm da ferramenta.
- Uso interno e de estudo (Resolução CVM 20).

## Portfólio → `portfolio_de_analises` / `adicionar_ao_portfolio` / `gerar_portfolio_pdf`
Só relatórios sem dados de cliente (a ferramenta bloqueia os outros). Sugira as análises com mais rigor e variedade
(empresa, fundos, renda fixa, macro). O PDF é amostra de trabalho: não distribuir recomendações a terceiros sem CNPI.

## Entrevista
Roda direto no Telegram (`/entrevista [cargo]`, `/entrevista fim`). Aqui: `iniciar_entrevista` / `responder_entrevista`
/ `encerrar_entrevista`. Cargos: analista_research, estrategista, analista_buyside, consultor_cvm, private_banker.

## Radar regulatório → `radar_regulatorio`
Fontes oficiais (CVM, Receita, Banco Central, Câmara). Para cada item 🔴: o que muda, para quem, a partir de quando e o
impacto prático para um assessor (clientes, produtos, tributação, obrigações). Se a fonte só trouxer a ementa, diga que
é preciso ler a norma no link antes de agir. Se alterar alíquota/limite, lembre de atualizar `config/regras_mercado.yaml`.
