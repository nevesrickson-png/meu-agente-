# Quíron Terminal — especificação

Tela interativa no estilo dos terminais profissionais de mercado: fundo escuro, alta densidade de informação,
operação pelo teclado, tudo atualizando sozinho. Nas Fases 0–4 roda no seu PC; depois, no host, aberto no navegador do PC e do celular pela rede Tailscale.
Nome e visual próprios: "Quíron Terminal" (não usar marcas de terceiros).

## Layout
- **Barra de comando** no topo (atalho `/` ou `Ctrl+K`): digite um código e Enter.
- **Grade de painéis** redimensionáveis e arrastáveis; layouts salvos ("Manhã", "Análise", "Estudo").
- **Faixa de cotações** rolando no rodapé (watchlist).
- **Painel de chat** lateral com o Quíron (mesmo agente do Telegram).
- Tema escuro com destaques âmbar/verde/vermelho; fonte monoespaçada nos números; modo claro opcional.

## Comandos da barra (estilo terminal)
| Comando | Abre |
|---|---|
| `PETR4` | Visão do ativo: cotação, gráfico, indicadores, notícias e posts relacionados |
| `PETR4 GP` | Gráfico avançado (períodos, médias, comparação com índice) |
| `PETR4 FA` | Demonstrações e indicadores fundamentalistas (CVM) |
| `PETR4 DCF` | Valuation (dispara análise no motor; resultado na aba Relatórios) |
| `TOP` | Principais notícias agora |
| `SOC` | Feed de redes (Bluesky, Reddit, YouTube) por tema |
| `ECO` | Agenda econômica (Copom, IPCA, payroll, PIB, resultados de empresas) |
| `CURV` | Curva de juros (ETTJ ANBIMA) e taxas do Tesouro |
| `MACRO` | Painel macro: Selic, IPCA, Focus, câmbio, fiscal, atividade |
| `WEI` | Índices mundiais |
| `FX` | Moedas |
| `CMDTY` | Commodities |
| `FUND <nome/CNPJ>` | Análise de fundo (CVM) |
| `CMPF` | Comparador de fundos |
| `PORT` | Carteira (cole/importe) com alocação, risco e stress |
| `CALC` | Calculadoras |
| `PLAN <CLI-XXX>` | Planejamento financeiro |
| `RPT` | Relatórios do Quíron (arquivo pesquisável) |
| `ACAD` | Academia: progresso, simulados, plano da semana |
| `TASK` | Tarefas e agenda do dia |
| `ALRT` | Alertas ativos |
| `HELP` | Lista de comandos |

## Painéis da v1
1. **Watchlist** — de `config/watchlist.yaml`, com variação do dia e mini-gráfico.
2. **Juros** — Selic, CDI, curva prefixada e real, taxas do Tesouro.
3. **Macro** — Focus (mediana e mudança semanal), IPCA 12m, câmbio, indicadores-chave.
4. **Notícias** — RSS de `config/fontes_noticias.yaml`, com filtro por tema e destaque para palavras-alerta.
5. **Redes** — Bluesky, Reddit e YouTube por tema, com resumo de sentimento.
6. **Agenda econômica** — calendários do IBGE, Banco Central, Copom e resultados de empresas.
7. **Calculadoras** — todas as de `/calc`, com resultado ao vivo enquanto você digita.
8. **Chat Quíron** — conversa com o agente (ativado depois da Fase 5); respostas podem abrir painéis.
9. **Status** — saúde do sistema, fila de análises, último backup.

## Painéis da v2
Telas de análise (`FA`, `DCF`, `PORT`, `FUND`, `CMPF`, `PLAN`), Relatórios, Academia, Tarefas e Alertas.

## Atualização dos dados
- Cotações: a cada 1–5 min (dados gratuitos da B3 têm atraso de ~15 min; o painel mostra o horário de cada dado).
- Notícias e redes: a cada 5–15 min.
- Macro/juros: diário ou na divulgação.
- Atualização na tela via WebSocket, sem recarregar a página.

## Requisitos técnicos
- Backend FastAPI que reutiliza os serviços dos MCP (sem duplicar lógica).
- Frontend leve e rápido; gráficos com lightweight-charts ou ECharts.
- Responsivo (funciona no celular), atalhos de teclado, layouts salvos por usuário.
- No host: acesso apenas pela Tailscale + senha.
