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
| 19º | **Fase 18 — Integrações** | Host + PC | CRM próprio e SDR | todas |

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
- [~] 1.1 `config/guia_22_blocos.yaml` — modelo pronto; **falta você preencher os 22 blocos** (depois: ferramenta `reclassificar`)
- [x] 1.2 MCP `quiron-biblioteca`: ingestão de PDF com texto, PDF escaneado (OCR por+eng) e EPUB
- [x] 1.3 Trechos com metadados (livro, autor, capítulo, página, bloco); embeddings multilíngues leves; Chroma
- [x] 1.4 Ficha por livro ligada aos 22 blocos + relatório de ingestão e cobertura
- [x] 1.5 Ferramentas: buscar com citação, estudar tema, debate de autores, mapa de autor, ficha, conectar conceitos
- [x] 1.6 Skills em `agente/skills/` para cada uso (estudo, debate, pílula diária)
**Teste de aceite:** no Claude Code, "me explica duration usando a biblioteca" traz resposta correta com livro e capítulo.
> ✅ 03/10/2026: aprovado com livros de teste (PDF, PDF escaneado com OCR e EPUB) — a resposta citou livro, capítulo e página. Falta: rodar com os seus 3 livros no PC (`uv run quiron-ingerir`) e preencher os 22 blocos.
```
Execute a FASE 1 do docs/00-ROTEIRO.md, item por item. Vou te passar meus 22 blocos.
Processe só os 3 livros do piloto (meu PC tem 8 GB). Ao final, marque os itens e explique o teste de aceite.
```

## FASE 2 — Dados de mercado (PC)
- [ ] 2.1 MCP `quiron-mercado`: Banco Central (SGS, Focus), Tesouro Transparente, ANBIMA (ETTJ), IBGE, brapi, yfinance
- [ ] 2.2 CVM Dados Abertos (companhias e fundos) e datasets do Damodaran
- [ ] 2.3 Cache em SQLite; fonte e horário em cada dado; aviso de atraso nas cotações
- [ ] 2.4 Agenda econômica (IBGE, BCB/Copom, resultados de empresas)
- [ ] 2.5 Ferramentas: cotação, taxas, curva, macro, agenda, briefing sob demanda
- [ ] 2.6 Skill do briefing (formato fixo, curto, o que importa para clientes)
**Teste de aceite:** no Claude Code, "faça meu briefing" traz dados corretos com fonte e horário.
```
Execute a FASE 2 do docs/00-ROTEIRO.md, item por item. Só fontes gratuitas e oficiais.
```

## FASE 3 — Notícias e redes (PC)
- [ ] 3.1 Confirmar feeds RSS ativos de `config/fontes_noticias.yaml`
- [ ] 3.2 MCP `quiron-noticias`: coleta, deduplicação, classificação por tema e ativo
- [ ] 3.3 Bluesky, Reddit e YouTube pelas APIs oficiais (me guie nas chaves gratuitas)
- [ ] 3.4 Ferramentas: notícias por tema, o que as redes dizem, resumo de sentimento, palavras-alerta
**Teste de aceite:** "o que está saindo sobre o Copom?" traz notícias e posts recentes com resumo e fontes.
```
Execute a FASE 3 do docs/00-ROTEIRO.md, item por item. Respeite termos de uso; prefira RSS e APIs oficiais.
```

## FASE 4 — Quíron Terminal v1 (PC)
- [ ] 4.1 Backend FastAPI reutilizando `quiron/servicos` + WebSocket
- [ ] 4.2 Frontend: grade de painéis, tema escuro, atalhos de teclado, layouts salvos
- [ ] 4.3 Barra de comando: `<TICKER>`, `GP`, `TOP`, `SOC`, `ECO`, `CURV`, `MACRO`, `WEI`, `FX`, `CMDTY`, `HELP`
- [ ] 4.4 Painéis: watchlist, juros, macro, notícias, redes, agenda, calculadoras básicas, status
- [ ] 4.5 Atalho para abrir no Windows com dois cliques (`Quíron Terminal.bat`)
- [ ] 4.6 Leve: consumo de memória compatível com 8 GB
**Teste de aceite:** você abre o Terminal no navegador, digita `PETR4` e `CURV`, e os dados atualizam sozinhos.
```
Execute a FASE 4 do docs/00-ROTEIRO.md seguindo o docs/06-TERMINAL.md. Leia a skill de frontend-design se disponível.
Quero visual profissional, denso, rápido e leve.
```

## FASE 5 — Agente 24h no Telegram
- [ ] 5.1 Teste comparativo de runtime (Hermes × bot próprio; Claude se houver orçamento) — `docs/07-DECISAO-RUNTIME.md`
- [ ] 5.2 **Você decide** o runtime e o host (`docs/03-HOSPEDAGEM.md`)
- [ ] 5.3 Preparar o host: `deploy/preparar_host.sh`, Docker Compose, Tailscale
- [ ] 5.4 Subir MCPs + Terminal + runtime no host
- [ ] 5.5 Telegram com lista branca (só seu ID); áudio com transcrição
- [ ] 5.6 Processar a **biblioteca completa** no host
- [ ] 5.7 Rotinas: briefing 7h30, limite de 3 mensagens automáticas/dia, fins de semana normais
- [ ] 5.8 Backup noturno (Google Drive) + **simulado de desastre** com `deploy/migrar.sh`
**Teste de aceite:** com o PC desligado, o Quíron responde no Telegram usando a biblioteca toda; a restauração funciona.
```
Execute a FASE 5 do docs/00-ROTEIRO.md. Comece pelo item 5.1 e me apresente o comparativo antes de eu decidir.
Depois me guie comando por comando, esperando minha confirmação.
```

## FASE 6 — Academia
- [ ] 6.1 MCP `quiron-academia` lendo `config/trilha_certificacoes.yaml`
- [ ] 6.2 Ingerir seu material em `academia/material/`
- [ ] 6.3 Pesquisar, confirmar e catalogar os gratuitos de `docs/05-MATERIAIS-GRATUITOS.md` (mostrar antes de baixar)
- [ ] 6.4 Edital do **CFP** mapeado em tópicos
- [ ] 6.5 Aula, questões (botões no Telegram), flashcards com revisão espaçada
- [ ] 6.6 Simulado, diagnóstico, plano de estudo (3–7h/semana), estudo de caso, painel de progresso
- [ ] 6.7 Estrutura pronta para o CNPI
**Teste de aceite:** mini-simulado do CFP gera diagnóstico e plano da semana.
```
Execute a FASE 6 do docs/00-ROTEIRO.md, item por item. Comece pelo CFP.
```

## FASE 7 — Motor de análise e calculadoras
- [ ] 7.1 MCP `quiron-analise`: fila de tarefas pesadas
- [ ] 7.2 Relatórios Markdown → PDF (capa, premissas, fontes, limitações) + planilha
- [ ] 7.3 Entrega: resumo + anexos no Telegram; arquivo pesquisável
- [ ] 7.4 Modos de colaboração (entregar/debater/contestar)
- [ ] 7.5 Calculadoras com testes conferíveis à mão (também no Terminal: `CALC`)
**Teste de aceite:** uma análise de teste chega com resumo, PDF e planilha coerentes.
```
Execute a FASE 7 do docs/00-ROTEIRO.md. Este motor será reaproveitado nas Fases 8 a 11; capriche na estrutura.
```

## FASE 8 — Carteiras, alocação e risco
- [ ] 8.1 Carteira (texto, print, planilha) · 8.2 Alocação por perfil · 8.3 Risco (vol, VaR, drawdown, duration)
- [ ] 8.4 Stress test · 8.5 Otimização · 8.6 Rebalanceamento com impostos · 8.7 Backtest
**Teste de aceite:** carteira fictícia gera relatório completo; stress "Selic +3 p.p." faz sentido.
```
Execute a FASE 8 do docs/00-ROTEIRO.md usando o motor da Fase 7.
```

## FASE 9 — Planejamento completo (padrão CFP)
- [ ] 9.1 Ficha CLI-XXX · 9.2 Plano completo · 9.3 Aposentadoria · 9.4 Sucessão (ITCMD por estado)
- [ ] 9.5 Tributário e proteção · 9.6 Módulo empresário (PF × PJ)
**Teste de aceite:** cliente fictício recebe plano que você revisaria como CFP.
```
Execute a FASE 9 do docs/00-ROTEIRO.md usando o motor da Fase 7.
```

## FASE 10 — Fundos e gestores
- [ ] 10.1 Análise de fundo · 10.2 Comparativo · 10.3 Gestoras · 10.4 Previdência e portabilidade · 10.5 Alternativos
**Teste de aceite:** comparativo de 3 fundos reais bate com a CVM.
```
Execute a FASE 10 do docs/00-ROTEIRO.md.
```

## FASE 11 — Valuation de empresas (uso interno)
- [ ] 11.1 Raio-X · 11.2 DCF, múltiplos e sensibilidade · 11.3 Debate de teses · 11.4 Setor e resultados
- [ ] 11.5 Rodapé obrigatório de uso interno
**Teste de aceite:** DCF de empresa real com premissas rastreáveis.
```
Execute a FASE 11 do docs/00-ROTEIRO.md.
```

## FASE 12 — Quíron Terminal v2
- [ ] 12.1 Telas `FA`, `DCF`, `PORT`, `FUND`, `CMPF`, `PLAN`
- [ ] 12.2 `RPT`, `ACAD`, `TASK`, `ALRT`
- [ ] 12.3 Chat com o agente dentro do Terminal
- [ ] 12.4 Acesso pelo celular via Tailscale
**Teste de aceite:** `WEGE3 DCF` dispara a análise e o relatório aparece em `RPT`.
```
Execute a FASE 12 do docs/00-ROTEIRO.md seguindo o docs/06-TERMINAL.md.
```

## FASE 13 — Assessoria do dia a dia
- [ ] 13.1 Dossiê de reunião · 13.2 Pós-reunião por áudio · 13.3 Treino com cliente simulado
- [ ] 13.4 Objeções, explicações, mensagens (RASCUNHO), vencimentos · 13.5 `/esquecer` (LGPD)
**Teste de aceite:** áudio pós-reunião vira resumo e tarefas; treino gera feedback útil.
```
Execute a FASE 13 do docs/00-ROTEIRO.md.
```

## FASE 14 — Organização
- [ ] 14.1 Tarefas por texto/áudio com lembretes · 14.2 Google Agenda · 14.3 Hoje, notas, metas, revisão semanal
**Teste de aceite:** "amanhã às 10h ligar para o CLI-012" vira tarefa e o lembrete chega.
```
Execute a FASE 14 do docs/00-ROTEIRO.md. Me guie na autorização do Google Agenda.
```

## FASE 15 — Carreira, diário e radar
- [ ] 15.1 Plano de carreira · 15.2 Diário de teses · 15.3 Portfólio de análises · 15.4 Simulação de entrevista · 15.5 Radar regulatório
**Teste de aceite:** radar aponta norma recente; diário gera revisão de teses.
```
Execute a FASE 15 do docs/00-ROTEIRO.md.
```

## FASE 16 — Versão offline (PC)
- [ ] 16.1 Ollama com modelo de 3–4B · 16.2 MCPs leves locais + cópia do índice · 16.3 Clientes reais criptografados
- [ ] 16.4 Terminal local com dados em cache · 16.5 Pasta portátil com atalho
**Teste de aceite:** sem internet, o Quíron consulta a biblioteca e mostra um cliente real.
```
Execute a FASE 16 do docs/00-ROTEIRO.md. Lembre: Windows com 8 GB de RAM.
```

## FASE 17 — Conteúdo
- [ ] 17.1 Pautas, roteiros, fios, banco de ideias · 17.2 Disclaimer e créditos automáticos
```
Execute a FASE 17 do docs/00-ROTEIRO.md.
```

## FASE 18 — Integrações
- [ ] 18.1 CRM próprio (nunca o da EQI) · 18.2 SDR (lead qualificado → dossiê) · 18.3 Sincronização com a versão offline
```
Execute a FASE 18 do docs/00-ROTEIRO.md. Antes, leia o CRM e o SDR e me proponha o desenho para eu aprovar.
```
