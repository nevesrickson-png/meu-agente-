# ROTEIRO DO PROJETO QUÍRON — fases, ordem e entregas

Regra: **uma fase por vez, na ordem.** A fase só termina com todos os itens marcados e o teste de aceite aprovado.
Marcação: `[ ]` a fazer · `[~]` em andamento · `[x]` pronto.

## Estratégia: ferramentas primeiro, agente depois
Começamos **hoje, no seu PC, sem servidor e sem custo**. Cada ferramenta nasce como servidor MCP e você já a usa
conversando com o Claude Code. A escolha do agente do Telegram (Hermes, Claude ou bot próprio) e do servidor 24h
fica para a Fase 5, quando você já terá testado o Quíron na prática. Nada construído antes é perdido.

## Visão geral da ordem

| Ordem | Fase | Onde | Resultado ao final | Depende de |
|---|---|---|---|---|
| 1º | **Fase 0 — Fundação** | PC | Projeto criado; cérebro grátis funcionando | — |
| 2º | **Fase 1 — Biblioteca e Mentor (piloto)** | PC | 3 livros indexados; você estuda com o Quíron pelo Claude Code | 0 |
| 3º | **Fase 2 — Dados de mercado** | PC | Cotações, juros, macro, agenda e briefing sob demanda | 0 |
| 4º | **Fase 3 — Notícias e redes** | PC | RSS, Bluesky, Reddit, YouTube com resumo por tema | 2 |
| 5º | **Fase 4 — Quíron Terminal v1** | PC | Tela estilo terminal com painéis ao vivo e barra de comando | 2, 3 |
| 6º | **Fase 5 — Agente 24h no Telegram** | Host | Runtime escolhido, servidor no ar, biblioteca completa, backup | 1–4 |
| 7º | **Fase 6 — Academia** | Host | Professor do CFP completo + materiais gratuitos catalogados | 5 |
| 8º | **Fase 7 — Motor de análise e calculadoras** | Host | Fila, relatórios PDF/planilha, modos de colaboração | 5 |
| 9º | **Fase 8 — Carteiras, alocação e risco** | Host | Análise de carteira, otimização, stress test | 7 |
| 10º | **Fase 9 — Planejamento completo (CFP)** | Host | Plano, aposentadoria, sucessão, tributos | 7 |
| 11º | **Fase 10 — Fundos e gestores** | Host | Análise e comparativos de fundos | 7 |
| 12º | **Fase 11 — Valuation de empresas** | Host | Raio-X, DCF, múltiplos, debate de teses | 7 |
| 13º | **Fase 12 — Quíron Terminal v2** | Host | Telas de análise, relatórios, academia, chat | 4, 8–11 |
| 14º | **Fase 13 — Assessoria do dia a dia** | Host | Reuniões, pós-reunião, treino com cliente simulado | 8, 9 |
| 15º | **Fase 14 — Organização** | Host | Tarefas, Google Agenda, revisão semanal | 5 |
| 16º | **Fase 15 — Carreira, diário e radar** | Host | Plano de carreira, diário de teses, monitor de normas | 6, 11 |
| 17º | **Fase 16 — Versão offline** | PC | Quíron sem internet, com clientes reais criptografados | 13, 14 |
| 18º | **Fase 17 — Conteúdo** | Host | Pautas, roteiros, banco de ideias | 3 |
| 19º | **Fase 18 — Integrações** ⏸️ adiada | Host + PC | CRM próprio e SDR | todas |

**Por que essa ordem:**
- As Fases 0–4 são leves, gratuitas e rodam no seu PC: você começa já e vê resultado em dias.
- A Academia (prioridade nº 1) vem logo após o servidor porque o processamento do material de estudo é pesado demais para 8 GB.
  Enquanto isso, a biblioteca piloto já serve de mentor.
- O motor de análise é construído uma vez e reaproveitado por carteiras, planejamento, fundos e valuation.

## Antes de começar (checklist do seu lado)
- [ ] Claude Code instalado e funcionando no seu PC
- [ ] Git instalado e conta no GitHub
- [ ] Chave gratuita do Gemini (Google AI Studio) — o Claude Code te guia
- [ ] 3 livros para o piloto em `biblioteca/entrada/` (de preferência 1 PDF com texto, 1 escaneado, 1 EPUB)
- [ ] Seus 22 blocos do guia à mão (Fase 1)

---

## FASE 0 — Fundação (PC)
- [x] 0.1 Claude Code lê CLAUDE.md, docs/ e config/, e faz até 5 perguntas
- [x] 0.2 Estrutura de pastas, `pyproject` (uv), `.gitignore`, repositório privado no GitHub
- [x] 0.3 `quiron/nucleo`: config, `cerebro.py` (LiteLLM: Gemini → Groq), com teste de conexão
- [x] 0.4 ~~`anonimizador.py`~~ — removido por decisão do Rickson (não digita dados de clientes)
- [~] 0.5 `regras_mercado.yaml` — **você confere e preenche `verificado_em`**
- [x] 0.6 `agente/persona.md` gerado de `config/persona.yaml`
- [x] 0.7 Esqueleto de servidor MCP + `.mcp.json` registrando-o no Claude Code (ferramenta de teste "ping")
**Teste de aceite:** no Claude Code, você pede "use a ferramenta ping do Quíron" e ela responde; os testes passam.
> ✅ 03/10/2026: aprovado no ambiente de desenvolvimento (32 testes passando; `ping` respondeu pelo Claude Code). Falta: conferir no seu PC (`LEIA-ME.md` → "Rodar no seu PC") e preencher `verificado_em` no item 0.5.
```
Leia o CLAUDE.md e todos os arquivos em docs/ e config/. Execute a FASE 0 do docs/00-ROTEIRO.md, item por item.
Antes de programar, me faça até 5 perguntas. Lembre que meu PC é Windows com 8 GB de RAM.
Diga o que eu preciso fazer do meu lado. Ao final, marque os itens e explique o teste de aceite.
```

## FASE 1 — Biblioteca e Mentor (piloto no PC)
- [x] 1.1 `config/guia_22_blocos.yaml` — modelo pronto. Pendência do Rickson: preencher os 22 blocos e rodar a ferramenta `reclassificar` (não reprocessa os livros)
- [x] 1.2 MCP `quiron-biblioteca`: ingestão de PDF com texto, PDF escaneado (OCR por+eng) e EPUB
- [x] 1.3 Trechos com metadados (livro, autor, capítulo, página, bloco); embeddings multilíngues leves; Chroma
- [x] 1.4 Ficha por livro ligada aos 22 blocos + relatório de ingestão e cobertura
- [x] 1.5 Ferramentas: buscar com citação, estudar tema, debate de autores, mapa de autor, ficha, conectar conceitos
- [x] 1.6 Skills em `agente/skills/` para cada uso (estudo, debate, pílula diária)
**Teste de aceite:** no Claude Code, "me explica duration usando a biblioteca" traz resposta correta com livro e capítulo.
> ✅ 03/10/2026: aprovado com livros de teste (PDF, PDF escaneado com OCR e EPUB) — a resposta citou livro, capítulo e página. **Fase 1 encerrada pelo Rickson em 03/10/2026.**
```
Execute a FASE 1 do docs/00-ROTEIRO.md, item por item. Vou te passar meus 22 blocos.
Processe só os 3 livros do piloto (meu PC tem 8 GB). Ao final, marque os itens e explique o teste de aceite.
```

## FASE 2 — Dados de mercado (PC)
- [x] 2.1 MCP `quiron-mercado`: Banco Central (SGS, Focus), Tesouro Transparente, ANBIMA (ETTJ), IBGE, brapi, yfinance
- [x] 2.2 CVM Dados Abertos (companhias e fundos) e datasets do Damodaran
- [x] 2.3 Cache em SQLite; fonte e horário em cada dado; aviso de atraso nas cotações
- [x] 2.4 Agenda econômica (IBGE, BCB/Copom, resultados de empresas)
- [x] 2.5 Ferramentas: cotação, taxas, curva, macro, agenda, briefing sob demanda
- [x] 2.6 Skill do briefing (formato fixo, curto, o que importa para clientes)
**Teste de aceite:** no Claude Code, "faça meu briefing" traz dados corretos com fonte e horário.
> ✅ 03/10/2026: aprovado com dados reais. 19/19 testes online passando; "faça meu briefing" trouxe Selic, CDI, Tesouro, IPCA, Focus, dólar, Ibovespa, S&P 500 e Brent com fonte e horário. Correções feitas no teste real: filtro do Focus (espaços como %20), plano B do SGS pelo web service oficial do BC (a api.bcb.gov.br recusa servidores fora do Brasil), datas futuras da Selic meta ignoradas, títulos do IBGE limpos, dias da semana em português, US$ nas commodities. Copom 2026 conferido no BC. Revisão final (mesma data): agenda do IBGE convertida de UTC para o horário de Brasília (o IPCA aparecia às 12h), só divulgações de indicadores (sem pesquisas experimentais) e com mês de referência; IFIX como índice (pts); brapi sem token cai no Yahoo e, se os dois falharem, a mensagem pede o `BRAPI_TOKEN`; atas de nov/dez e reuniões de 2027 do Copom incluídas. Saída do teste de aceite em `docs/aceite/fase2-briefing-2026-10-03.md`.
```
Execute a FASE 2 do docs/00-ROTEIRO.md, item por item. Só fontes gratuitas e oficiais.
```

## FASE 3 — Notícias e redes (PC)
- [x] 3.1 Confirmar feeds RSS ativos de `config/fontes_noticias.yaml`
- [x] 3.2 MCP `quiron-noticias`: coleta, deduplicação, classificação por tema e ativo
- [~] 3.3 Bluesky, Reddit e YouTube pelas APIs oficiais (me guie nas chaves gratuitas) — código e guia prontos (testados com respostas simuladas); **falta você criar as chaves** (`LEIA-ME.md`)
- [x] 3.4 Ferramentas: notícias por tema, o que as redes dizem, resumo de sentimento, palavras-alerta
**Teste de aceite:** "o que está saindo sobre o Copom?" traz notícias e posts recentes com resumo e fontes.
> ✅ 03/10/2026: aprovado para notícias — 14 feeds reais ativos (InfoMoney, Valor, E-Investidor, Folha, Exame, Bloomberg Línea, CNBC, FT, Economist, BC ×3, CVM, IBGE); a resposta trouxe fatos com fonte, horário e link, oficial antes da imprensa. Sem RSS oficial: Reuters, Tesouro, ANBIMA, B3. Posts das redes entram quando as chaves forem criadas (3.3). O histórico de notícias cresce com o uso (os feeds só guardam ~1 dia).
```
Execute a FASE 3 do docs/00-ROTEIRO.md, item por item. Respeite termos de uso; prefira RSS e APIs oficiais.
```

## FASE 4 — Quíron Terminal v1 (PC)
- [x] 4.1 Backend FastAPI reutilizando `quiron/servicos` + WebSocket
- [x] 4.2 Frontend: grade de painéis, tema escuro, atalhos de teclado, layouts salvos
- [x] 4.3 Barra de comando: `<TICKER>`, `GP`, `TOP`, `SOC`, `ECO`, `CURV`, `MACRO`, `WEI`, `FX`, `CMDTY`, `HELP`
- [x] 4.4 Painéis: watchlist, juros, macro, notícias, redes, agenda, calculadoras básicas, status
- [x] 4.5 Atalho para abrir no Windows com dois cliques (`Quíron Terminal.bat`)
- [x] 4.6 Leve: consumo de memória compatível com 8 GB
**Teste de aceite:** você abre o Terminal no navegador, digita `PETR4` e `CURV`, e os dados atualizam sozinhos.
> ✅ 03/10/2026: aprovado num navegador real (Chromium) com dados reais — teste automático `testes/test_terminal_navegador.py` digita PETR4 e CURV, confere cotação, curva ANBIMA e a atualização automática sem recarregar. Memória do Terminal ≈ 180 MB. Telas: `docs/img/terminal-v1.png` e `docs/img/terminal-v1-grafico.png`. Falta: você abrir no seu PC pelo `Quiron Terminal.bat`.
```
Execute a FASE 4 do docs/00-ROTEIRO.md seguindo o docs/06-TERMINAL.md. Leia a skill de frontend-design se disponível.
Quero visual profissional, denso, rápido e leve.
```

## FASE 5 — Agente 24h no Telegram
- [x] 5.1 Teste comparativo de runtime (Hermes × bot próprio; Claude se houver orçamento) — `docs/07-DECISAO-RUNTIME.md`
  > 04/10/2026: os dois runtimes estão montados e ligados às ferramentas do Quíron; o roteiro de 10 pedidos está pronto (`uv run quiron-comparativo`). O Rickson decidiu pelo bot próprio; o comparativo segue disponível como régua de qualidade.
- [x] 5.2 **Você decide** o runtime e o host (`docs/03-HOSPEDAGEM.md`) — **runtime decidido em 04/10/2026: bot próprio** com o melhor de Hermes, Claude Code e OpenClaw (`docs/08-AGENTE-QUIRON.md`). **Host decidido em 04/10/2026: PC Windows agora → mini PC em casa → VPS no futuro** (custo mínimo; `docs/03-HOSPEDAGEM.md`).
- [~] 5.3 Preparar o host: `deploy/preparar_host.sh`, Docker Compose, Tailscale — **pacote pronto e testado** (imagem Docker construída, agente respondeu de dentro do contêiner). Falta rodar no host escolhido.
- [~] 5.4 Subir MCPs + Terminal + runtime no host — etapa 1 (PC): `Quiron Telegram.bat` + `Quiron Inicio Automatico.bat`; etapa 2: mini PC
- [x] 5.5 Telegram com lista branca (só seu ID); áudio com transcrição (Whisper grátis do Groq)
- [ ] 5.6 Processar a **biblioteca completa** no host
- [x] 5.7 Rotinas: briefing 7h30 (criado sozinho na 1ª vez, com pré-aquecimento às 7h10), limite de 3 mensagens automáticas/dia, fins de semana normais
- [~] 5.8 Backup noturno (Google Drive) + **simulado de desastre** com `deploy/migrar.sh` — scripts prontos (`backup.sh`, `restaurar.sh`, `migrar.sh`); simulado no host.
**Teste de aceite:** com o PC desligado, o Quíron responde no Telegram usando a biblioteca toda; a restauração funciona.
> 04/10/2026 — **etapa 1 (PC) aprovada pelo Rickson**: instala/atualiza/abre com um clique (`Abrir Quiron.bat`), tela de
> Configurações, bot respondendo no Telegram. O aceite completo (PC desligado + restauração) fica para a etapa 2 (mini PC):
> itens 5.4 (host), 5.6 e 5.8 seguem abertos. Por decisão do Rickson, seguimos para a Fase 6 enquanto isso.
```
Execute a FASE 5 do docs/00-ROTEIRO.md. Comece pelo item 5.1 e me apresente o comparativo antes de eu decidir.
Depois me guie comando por comando, esperando minha confirmação.
```

## FASE 6 — Academia
- [x] 6.1 MCP `quiron-academia` lendo `config/trilha_certificacoes.yaml` (10 ferramentas: trilha, edital, tópico, diagnóstico, plano, configurar, gerar/questões, registrar, materiais)
- [~] 6.2 Ingerir seu material em `academia/material/` — comando pronto: `uv run quiron-ingerir --academia` (subpastas por certificação). **Falta você colocar as apostilas.**
- [x] 6.3 Pesquisar, confirmar e catalogar os gratuitos de `docs/05-MATERIAIS-GRATUITOS.md` (mostrar antes de baixar) — `config/materiais_gratuitos.yaml` (16 itens, links conferidos em 04/10/2026; nada baixado sem sua aprovação)
- [x] 6.4 Edital do **CFP** mapeado em tópicos — `config/editais/CFP.yaml` gerado do Programa Detalhado oficial: 8 módulos, pesos, tempos e 922 tópicos
- [x] 6.5 Aula, questões (botões no Telegram), flashcards com revisão espaçada — `/aula`, `/questoes` (A–D, ⚠ anula), `/flashcards` (SM-2); questões geradas pelo Groq e conferidas pelo Gemini (contas conferidas em Python)
- [x] 6.6 Simulado, diagnóstico, plano de estudo (3–7h/semana), estudo de caso, painel de progresso — `/simulado`, `/diagnostico`, `/plano`, `/caso`, `/academia`
- [~] 6.7 Estrutura pronta para o CNPI — banco, diagnóstico e MCP já aceitam outra certificação (`cert`); falta o programa oficial do CNPI (não achei o PDF no site da Apimec em 04/10/2026)
- [x] 6.8 (pedido do Rickson, 04/10/2026) **Academia de todas as áreas**: 20 campos de conhecimento com programa próprio (`config/editais/<CAMPO>.yaml`, editável) + certificações; `/area` troca a área; áreas novas criadas pelo Rickson
- [x] 6.9 (pedido do Rickson) **Acervo**: tela de upload no Terminal (`/acervo`, atalho *Quiron - Acervo*) — escolhe a área, arrasta o PDF/EPUB, o arquivo vai para `biblioteca/acervo/<área>/` e entra na biblioteca marcado com a área
**Teste de aceite:** mini-simulado do CFP gera diagnóstico e plano da semana.
```
Execute a FASE 6 do docs/00-ROTEIRO.md, item por item. Comece pelo CFP.
```

## FASE 7 — Motor de análise e calculadoras
- [x] 7.1 MCP `quiron-analise`: fila de tarefas pesadas — `dados/analise.db`, reserva atômica, tarefa órfã volta à fila, tipos registrados com `@tipo`
- [x] 7.2 Relatórios Markdown → PDF (capa, premissas, fontes, limitações) + planilha — PDF com pymupdf (sem dependência de sistema, roda igual no Windows), gráficos matplotlib (paleta validada), planilha openpyxl
- [x] 7.3 Entrega: resumo + anexos no Telegram; arquivo pesquisável — o bot envia resumo + PDF + planilha quando fica pronto; busca em texto completo (Terminal `RPT`, MCP `relatorios`)
- [x] 7.4 Modos de colaboração (entregar/debater/contestar) — redação a partir dos números calculados; todo número do texto é conferido (inventado → nova tentativa → aviso)
- [x] 7.5 Calculadoras com testes conferíveis à mão (também no Terminal: `CALC`) — 11 calculadoras (novas: financiamento Price/SAC, VPL/TIR, aporte p/ meta, renda na aposentadoria, PU prefixado, duration); `/calc` no Telegram
**Teste de aceite:** uma análise de teste chega com resumo, PDF e planilha coerentes.
> ✅ 04/10/2026: pedido em linguagem natural ao agente (“R$ 300 mil, 2 anos, CDB 108% × LCI 90% × Tesouro Selic × IPCA+, modo debate”) → análise #1 com taxas reais (BCB, Focus, Tesouro) → resumo + PDF de 4 páginas + planilha coerentes, números do texto conferidos. Falta: você testar pelo Telegram.
```
Execute a FASE 7 do docs/00-ROTEIRO.md. Este motor será reaproveitado nas Fases 8 a 11; capriche na estrutura.
```

## FASE 8 — Carteiras, alocação e risco
- [x] 8.1 Carteira (texto, print, planilha) — texto pelo cérebro (plano B por regras), planilha xlsx/csv com colunas reconhecidas, print por OCR local (tesseract) com CPF/conta/e-mail/telefone ocultados antes do modelo; guardada como `CART-…` (`dados/carteiras/`)
- [x] 8.2 Alocação por perfil — faixas [mín, alvo, máx] por classe em `config/alocacao_perfis.yaml` (conservador/moderado/arrojado, editável); enquadramento no relatório
- [x] 8.3 Risco (vol, VaR, drawdown, duration) — 60 meses mensais; ticker próprio ou proxy da classe (CDI, índices sintéticos do Tesouro, Ibovespa, cesta de FIIs, S&P em reais); VaR/CVaR, beta, contribuição ao risco
- [x] 8.4 Stress test — hipotéticos editáveis (`config/cenarios_stress.yaml`: Selic ±3 p.p., bolsa −20%, dólar +20%, inflação +3 p.p.) + 6 episódios históricos
- [x] 8.5 Otimização — média-variância dentro das faixas do perfil (máx. Sharpe, mín. variância, fronteira); retornos esperados declarados em `config/premissas_carteira.yaml`
- [x] 8.6 Rebalanceamento com impostos — aporte primeiro; vendas pelo menor IR (prejuízo, isentos, isenção de R$ 20 mil em ações, FII 20%, ETF 15%, tabela regressiva); aporte para chegar ao alvo sem vender
- [x] 8.7 Backtest — 10 anos, rebalanceamento mensal: atual × alvo × ótima × CDI × Ibovespa
**Teste de aceite:** carteira fictícia gera relatório completo; stress "Selic +3 p.p." faz sentido.
✅ Aceite (04/10/2026): carteira moderada fictícia de R$ 566 mil (CLI-012) → PDF de 9 páginas; Selic +3 p.p. = −4,35%
(IPCA+ 2035 −R$ 10,8 mil por duration modificada 8,0 × 1,5 p.p.; prefixado −R$ 2,4 mil; ações pelo beta; FII −8%;
IVVB11 +5% pelo dólar) com +R$ 6 mil de carregamento do pós-fixado em 12 meses.
```
Execute a FASE 8 do docs/00-ROTEIRO.md usando o motor da Fase 7.
```

## FASE 9 — Planejamento completo (padrão CFP)
- [x] 9.1 Ficha CLI-XXX — MCP `quiron-assessoria` (montada conversando, mescla, histórico de versões em `dados/fichas/`); `/esquecer CLI-XXX` apaga tudo do cliente (LGPD)
- [x] 9.2 Plano completo — diagnóstico (fluxo, balanço, indicadores), objetivos, orçamento de aportes × sobra e plano de ação priorizado
- [x] 9.3 Aposentadoria — capital necessário com INSS, aporte (cenário médio e 85% de chance no Monte Carlo), renda sustentável, aporte que cabe no orçamento, sensibilidade
- [x] 9.4 Sucessão (ITCMD por estado) — meação por regime de bens, herança, ITCMD (máxima da faixa da UF), inventário, liquidez fora do inventário, instrumentos
- [x] 9.5 Tributário e proteção — completa × simplificada, PGBL ideal, imposto mínimo de alta renda; seguro de vida pelo método das necessidades, invalidez, reserva e saúde
- [x] 9.6 Módulo empresário (PF × PJ) — PF autônomo × Simples III (fator R) × Simples V × Lucro Presumido, líquido do dono
**Teste de aceite:** cliente fictício recebe plano que você revisaria como CFP.
✅ Aceite (04/10/2026): CLI-101 fictício (45 anos, SP, casado, 2 filhos, empresário) → PDF de 9 páginas com plano de ação;
o plano mostra que a meta de R$ 25 mil/mês aos 60 tem 3% de chance com o aporte atual (85% exige R$ 27,3 mil/mês, acima
da sobra de R$ 16,8 mil) e propõe as alavancas; falta de R$ 313 mil em seguro de vida e de R$ 1,35 mi em invalidez.
```
Execute a FASE 9 do docs/00-ROTEIRO.md usando o motor da Fase 7.
```

## FASE 10 — Fundos e gestores
- [x] 10.1 Análise de fundo — CVM Dados Abertos (cadastro CVM 175, informe diário resumido num índice mensal de todos os fundos em `dados/fundos.db`, extrato com taxas/prazos): rentabilidade por janela × CDI/Ibovespa, % do CDI, risco, percentil entre os pares ANBIMA, fluxo, cotistas, taxas e liquidez
- [x] 10.2 Comparativo — 2 a 6 fundos lado a lado + tabela de conferência das cotas na CVM
- [x] 10.3 Gestoras — patrimônio por classificação (sem fundos de cotas), maiores fundos abertos, consistência contra os pares, captação
- [x] 10.4 Previdência e portabilidade — atual × destino, projeção do saldo, tabela regressiva × progressiva
- [x] 10.5 Alternativos — FII com o informe mensal da CVM (VP, P/VP, DY sobre o preço com proventos pagos, rentabilidade, segmento) e guia de FIDC/FIP/COE na skill
**Teste de aceite:** comparativo de 3 fundos reais bate com a CVM.
✅ Aceite (04/10/2026): CSHG Verde 30, Legacy Capital Advisory e Ibiuna Hedge — as 6 cotas da conferência (30/09/2025,
29/09/2023 e 30/09/2026) são idênticas às dos arquivos brutos do informe diário da CVM (`testes/test_fundos_online.py`).
```
Execute a FASE 10 do docs/00-ROTEIRO.md.
```

## FASE 11 — Valuation de empresas (uso interno)
- [x] 11.1 Raio-X — DFP/ITR/FCA da CVM (contas padronizadas, LTM, ações, tickers, setor): histórico de 5 anos, margens e múltiplos
- [x] 11.2 DCF, múltiplos e sensibilidade — WACC (Treasury ^TNX + Damodaran ERP/risco-país/β de setor + Focus), DCF de 10 anos com perpetuidade g ÷ ROIC, cenários, β de regressão, sensibilidade WACC × g
- [x] 11.3 Debate de teses — DCF reverso (crescimento e WACC implícitos no preço), pontos a favor/contra calculados, modos debater/contestar, comando /tese
- [x] 11.4 Setor e resultados — `setor_multiplos` (pares, medianas, preço implícito) e `resultado_trimestral` (trimestre × ano anterior, acumulado, alavancagem)
- [x] 11.5 Rodapé obrigatório de uso interno — "Uso interno — não constitui relatório de análise (Resolução CVM 20)" em todo relatório de empresa
**Teste de aceite:** DCF de empresa real com premissas rastreáveis.
✅ Aceite (05/10/2026): DCF da WEG (WEGE3) — receita conferida no arquivo bruto da DFP; cada componente do WACC com
fonte; premissas de projeção com a conta que as gerou; DCF reverso mostra que o preço embute WACC de ~7,7% ou crescimento
de ~59% (`testes/test_valuation_online.py`).
```
Execute a FASE 11 do docs/00-ROTEIRO.md.
```

## FASE 12 — Quíron Terminal v2
- [x] 12.1 Telas `FA` (demonstrações da CVM + múltiplos), `DCF` (dispara `valuation_dcf` na fila), `PORT` (carteira colada →
  enquadramento + diagnóstico), `FUND` (busca na CVM → análise), `CMPF` (2–6 fundos), `PLAN` (fichas CLI-XXX → relatórios)
- [x] 12.2 `RPT` (destaca a análise pedida e se atualiza até ficar pronta), `ACAD` (domínio por módulo), `TASK` (tarefas e
  lembretes do Telegram), `ALRT` (alertas de preço, variação e notícia — o bot avisa a cada 5 min)
- [x] 12.3 Chat com o agente dentro do Terminal (`CHAT`: mesma persona, ferramentas, aprovações e compliance; conversa própria)
- [x] 12.4 Acesso pelo celular via Tailscale (layout de uma coluna, toque confortável, "adicionar à tela inicial"; ações
  exigem o cabeçalho da tela e, sem senha, só o PC ou o endereço `.ts.net`)
**Teste de aceite:** `WEGE3 DCF` dispara a análise e o relatório aparece em `RPT`.
✅ Aceite (05/10/2026): no navegador, `WEGE3 DCF` pôs a análise na fila, o RPT destacou a tarefa e mostrou o PDF do
valuation da WEG pronto em ~1 minuto (`testes/test_terminal_navegador.py -m online`).
```
Execute a FASE 12 do docs/00-ROTEIRO.md seguindo o docs/06-TERMINAL.md.
```

## FASE 13 — Assessoria do dia a dia
- [x] 13.1 Dossiê de reunião (`/reuniao CLI-XXX`: ficha, carteira e enquadramento, vencimentos, últimas reuniões,
  lembretes e relatórios → roteiro) · 13.2 Pós-reunião por áudio (`/pos CLI-XXX` + áudio → resumo, decisões, tarefas com
  prazos calculados em Python, lembretes, sugestões para a ficha com botão, alertas de compliance) · 13.3 Treino com
  cliente simulado (`/treino`: 5 personagens, 5 cenários, 3 dificuldades; feedback com métricas calculadas + rubrica)
- [x] 13.4 Objeções (`config/objecoes.yaml`), explicações, mensagens (RASCUNHO + `conferir_compliance`), vencimentos
  das carteiras · 13.5 `/esquecer` (LGPD) também apaga anotações de reunião e lembretes do cliente
**Teste de aceite:** áudio pós-reunião vira resumo e tarefas; treino gera feedback útil.
✅ Aceite (05/10/2026): um áudio falado (voz sintética em português) foi transcrito pelo Whisper e virou resumo,
3 tarefas (sexta e amanhã calculadas, 1 com prazo sugerido), lembrete da próxima reunião e sugestões para a ficha; um
treino com o "Dr. Henrique" gerou nota por critério, objetivo oculto descoberto, compliance zerado pela promessa de 20%
e reescrita da frase (`testes/test_assessoria_online.py`).
```
Execute a FASE 13 do docs/00-ROTEIRO.md.
```

## FASE 14 — Organização
- [x] 14.1 Tarefas por texto/áudio com lembretes (`/tarefa` ou frase livre; data/hora calculadas em Python; lembrete
  com botões ✅ Feito / ⏰ +1h / 📅 Amanhã; `/tarefas`, `/feito`, `/adiar`) · 14.2 Google Agenda (API oficial, OAuth
  do próprio Rickson — guia em `docs/09-GOOGLE-AGENDA.md`; `/evento`, eventos no `/hoje` e na revisão) · 14.3 `/hoje`,
  `/nota`/`/notas` (busca sem acento, #tags), `/meta` (semanal, mensal ou com prazo, ritmo calculado), `/revisao`
  (automática domingo 18h)
**Teste de aceite:** "amanhã às 10h ligar para o CLI-012" vira tarefa e o lembrete chega.
✅ Aceite (05/10/2026): a frase, mandada sem comando ao agente real, virou a tarefa #1 para 06/10 10:00 e o lembrete
chegou na hora com os botões; o mesmo por áudio ("Amanhã às dez horas, ligar para o contador")
(`testes/test_organizacao_online.py`). Google Agenda testado com respostas simuladas; a autorização é do Rickson.
```
Execute a FASE 14 do docs/00-ROTEIRO.md. Me guie na autorização do Google Agenda.
```

## FASE 15 — Carreira, diário e radar
- [x] 15.1 Plano de carreira (`/carreira`: trilha com prontidão da Academia, datas de prova e semanas necessárias,
  track record, portfólio, competências, próximos 90 dias) · 15.2 Diário de teses (`/diario`: premissas, invalidação,
  horizonte e confiança; preço do dia; lembrete de revisão; retorno × Ibovespa e calibração Brier calculados) ·
  15.3 Portfólio de análises (`/portfolio`: só relatórios sem cliente; PDF com resumos + track record) · 15.4 Simulação
  de entrevista (`/entrevista`: 5 cargos, feedback com métricas + rubrica) · 15.5 Radar regulatório (`/radar`: CVM,
  Receita, Banco Central e Câmara, por relevância; automático às segundas 8h20)
**Teste de aceite:** radar aponta norma recente; diário gera revisão de teses.
✅ Aceite (05/10/2026): o radar trouxe, de fontes oficiais, a Resolução CMN 5.343 (FIDC, 24/09) e o PLP 255/2026
(previdência complementar) como 🔴; uma tese sobre WEGE3 registrada "há 6 meses" (fechamentos reais do Yahoo) foi
revisada com retorno, Ibovespa, excesso e premissas (`testes/test_carreira_online.py`).
```
Execute a FASE 15 do docs/00-ROTEIRO.md.
```

## FASE 16 — Versão offline (PC)
- [x] 16.1 Ollama com modelo de 3–4B (`QUIRON_MODO=offline` → só `ollama_chat/qwen2.5:3b`, contexto de 8 mil tokens,
  prompt curto) · 16.2 MCPs leves locais (biblioteca, fichas, tarefas, calculadoras — 9 ferramentas, só parâmetros
  obrigatórios) + cópia do índice (`quiron-offline pacote | importar | baixar`) · 16.3 Clientes reais criptografados
  (`cofre/clientes.cofre`, Scrypt + Fernet; só abre offline, sem modelo de nuvem e só em 127.0.0.1; tela CLI)
- [x] 16.4 Terminal local com dados em cache (rede nunca é tentada: último dado marcado DESATUALIZADO; selo OFFLINE;
  BIB = biblioteca) · 16.5 Pasta portátil com atalho (`Quiron Offline.bat` + atalho "Quiron - Offline"; guia
  `docs/10-OFFLINE.md`)
**Teste de aceite:** sem internet, o Quíron consulta a biblioteca e mostra um cliente real.
✅ Aceite (05/10/2026): com a internet do processo cortada, o Terminal offline destrancou o cofre e mostrou "Marcos
Antônio Pereira" (CLI-012) com o dossiê; o Quíron local (qwen2.5 3B no Ollama, CPU) buscou na biblioteca e respondeu
citando "Manual de Renda Fixa do Quíron, p. 1–2" em ~1 minuto (`testes/test_offline_aceite.py`).
```
Execute a FASE 16 do docs/00-ROTEIRO.md. Lembre: Windows com 8 GB de RAM.
```

## FASE 17 — Conteúdo
- [x] 17.1 Pautas, roteiros, fios, banco de ideias (`/pauta`, `/roteiro reels|youtube|carrossel|fio|artigo`, `/fio`,
  `/ideia`, `/ideias`; insumos numerados com fonte: Banco Central, regras oficiais com contas em Python, radar, notícias,
  agenda e biblioteca) · 17.2 Disclaimer e créditos automáticos (compliance com reescrita automática, todo número com %
  ou R$ conferido com as fontes, créditos só do que foi citado, disclaimer + aviso CVM 20 se citar empresa + aviso de IA;
  sai como RASCUNHO; `/conferir` para textos do Rickson)
✅ Aceite (05/10/2026): com dados reais, 4 pautas com fontes e um carrossel "Tesouro Selic ou poupança" sem alerta de
compliance, todos os números conferidos (Selic 13,75% do BC, regra da poupança 6,17% a.a. + TR e a conta de 4,98 p.p. a
favor do Tesouro Selic líquido), disclaimer e créditos (`testes/test_conteudo_online.py`).
```
Execute a FASE 17 do docs/00-ROTEIRO.md.
```

## FASE 18 — Integrações
- [~] 18.1 CRM próprio (nunca o da EQI) · 18.2 SDR (lead qualificado → dossiê) · 18.3 Sincronização com a versão offline
> ⏸️ 05/10/2026: desenho proposto e **adiado pelo Rickson** ("depois vou integrar com o CRM") — `docs/11-INTEGRACOES.md`.
```
Execute a FASE 18 do docs/00-ROTEIRO.md. Antes, leia o CRM e o SDR e me proponha o desenho para eu aprovar.
```

---

## Interface única (05/10/2026) — pedido do Rickson: "um sistema só com configurações e tudo junto"
- [x] Um atalho (**Quiron**) abre tudo: Terminal + Acervo + Configurações em abas, com o Telegram ligado e supervisionado
  (religa sozinho, registro na tela, nunca dois bots ao mesmo tempo)
- [x] Aba CONFIGURAÇÕES: visão geral, chaves (testar, descobrir ID; salvar reinicia o bot), Google Agenda (credencial +
  conectar), versão offline (verificar + trocar de modo com um clique), início automático com o Windows, versão
- [x] Atalhos soltos aposentados (Terminal, Acervo, Configurações, Google Agenda, Início automático); ficam **Quiron** e
  **Quiron - Offline**
✅ Aceite (05/10/2026): navegador real — abas e selo em todas as telas, primeiro uso abre CONFIGURAÇÕES, troca
normal → offline → normal pela tela em ~8 s, sem rolagem lateral no celular; 215 testes (`testes/test_central.py`).
Falta: você abrir pelo atalho no seu PC e salvar as chaves por lá uma vez para ver o Telegram ligar.

## Depuração geral (05/10/2026) — pedido do Rickson: "debugar o sistema todo e implementar melhorias"
- [x] Análise estática, 224 testes, teste de fumaça de todos os comandos do Telegram e painéis do Terminal, agente real
  (IA + ferramentas) respondendo com fonte
- [x] Bot: nunca fica mudo em erro, não perde mensagens no reinício, menu "/", `/sair`, modos que não sequestram conversas
- [x] Configurações: "Verificar tudo"; motivo claro quando o Telegram cai (ex.: token recusado); lançador explica porta ocupada
- [x] Cálculos e datas: IOF < 30 dias; "próxima sexta", "meio-dia", "daqui a 2 horas"

## Memória persistente (05/10/2026) — pedido do Rickson: "o melhor mecanismo possível de memória persistente"
- [x] Fatos aprendidos sozinhos das conversas (categoria, importância, atualização, privacidade), episódios permanentes,
  eventos dos comandos, recuperação automática por significado + palavras, consolidação noturna, `MEMORIA.md` editável
- [x] `/memoria` (ver, conversas, buscar, esquecer, mudar), `/lembrar`, `/novo` sem perder nada, LGPD apaga a memória do cliente
✅ Aceite (05/10/2026) com a IA real: numa conversa ele contou prova do CFP, horário de estudo, público e preferência
(sem dizer "lembre"); o escriba guardou 3 fatos e o resumo; em OUTRA conversa o Quíron respondeu certo, sem ferramentas.
239 testes (`testes/test_memoria_longa.py`). Falta: você conversar uns dias e conferir com `/memoria`.

---

## Depois do roteiro — pendências do seu lado (05/10/2026)
Todas as fases foram construídas e aprovadas no ambiente de desenvolvimento, menos a 18 (adiada). O que falta é colocar no ar:
- [ ] 5.3/5.4 Rodar no host definitivo (mini PC): `deploy/preparar_host.sh` + `deploy/instalar.sh` (`docs/03-HOSPEDAGEM.md`)
- [ ] 5.6 Processar a biblioteca completa no host
- [ ] 5.8 Simulado de desastre: `deploy/backup.sh` → `deploy/migrar.sh` em outra máquina
- [ ] 0.5 Conferir `config/regras_mercado.yaml` e preencher `verificado_em`
- [ ] 1.1 Preencher os 22 blocos em `config/guia_22_blocos.yaml` e rodar `reclassificar`
- [ ] Deixar os repositórios do GitHub como **privados** (hoje estão públicos)
- [ ] Fase 18 quando quiser: responder as 3 perguntas de `docs/11-INTEGRACOES.md`

