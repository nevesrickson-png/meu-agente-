# CLAUDE.md — Projeto Quíron

## Quem é o dono
Rickson Messias, assessor de investimentos, certificação CEA, solo, modelo comissionado.
Objetivo de carreira (5–10 anos): **analista/estrategista de referência**. Estuda 3–7h/semana (CFP primeiro, depois CNPI).
Clientes: empresários, profissionais liberais, aposentados/conservadores. Produtos: renda fixa/Tesouro, fundos/previdência,
renda variável, internacional. Também produz conteúdo de finanças com IA.
Ele não é programador: explique decisões em português simples, peça confirmação antes de mudanças grandes e diga
exatamente o que ele precisa fazer do lado dele.

## Propriedade e independência
- O Quíron é um sistema **pessoal e de propriedade exclusiva do Rickson**. Não é da EQI, não usa marca, sistemas,
  bases ou dados internos da EQI e não se conecta a eles. O mesmo vale para o CRM próprio e o SDR.
- Clientes da EQI têm notas no CRM da empresa: o Quíron **nunca** se conecta a ele. Dados desses clientes só entram
  digitados/colados pelo Rickson, identificados só como `CLI-XXX`.
- A atividade dele como assessor segue a Resolução CVM 178 e a LGPD; as regras de compliance abaixo valem sempre.

## O que é o Quíron
Um **parceiro de análise de nível especialista** (repertório de CFP, CFA, CAIA, FRM, CGA/CGE e CNPI, e além),
com postura de colega sênior direto e franco. Colabora, pensa junto e às vezes assume sozinho análises pesadas.
Também é professor nas certificações. Duas faces:
1. **Agente no Telegram** — conversa, executa funções, análises, briefing e lembretes.
2. **Quíron Terminal** — tela interativa estilo terminal profissional de mercado (`docs/06-TERMINAL.md`).
Prioridades: (1) conhecimento e estudo, (2) análise e assessoria, (3) organização, (4) conteúdo.
Funcionalidades em `docs/01-FUNCIONALIDADES.md`. Persona em `config/persona.yaml` (siga à risca).

## Princípio de arquitetura: FERRAMENTAS PRIMEIRO, AGENTE DEPOIS
- **Runtime decidido (04/10/2026): bot próprio em Python**, inspirado no melhor de Hermes, Claude Code e OpenClaw —
  desenho em `docs/08-AGENTE-QUIRON.md`. Sem terminal, arquivos do sistema, navegador autônomo nem loja de skills de terceiros.
- Por isso, toda a inteligência do Quíron é construída como **servidores MCP em Python**, independentes de runtime:
  `quiron-sistema` (ping e status — Fase 0), `quiron-biblioteca`, `quiron-academia`, `quiron-mercado`, `quiron-noticias`, `quiron-analise`, `quiron-assessoria`, `quiron-carreira`.
  Qualquer runtime que fale MCP usa essas ferramentas sem mudança de código.
- **Durante o desenvolvimento, o próprio Claude Code é a interface de teste:** os MCP são registrados no `.mcp.json`
  do projeto, e o Rickson já usa as ferramentas conversando com o Claude Code, antes de existir Telegram.
- As instruções de comportamento ficam em **arquivos Markdown de skills/prompts** (`agente/skills/`), escritos de forma
  neutra para serem reaproveitados por qualquer runtime.
- O **Quíron Terminal** (FastAPI + frontend) reutiliza os mesmos serviços dos MCP; não depende do runtime.
- Nunca acoplar código de negócio a um runtime específico.

## Infraestrutura
- **Fases 0 a 4 rodam no PC do Rickson** (Windows, até 8 GB de RAM), com `uv`, sem Docker: leve e imediato.
  Só o piloto da biblioteca (3 livros) é processado no PC.
- **A partir da Fase 5**, tudo vai para um host Linux 24h (Oracle Cloud, mini PC ou outro — `docs/03-HOSPEDAGEM.md`),
  em Docker Compose, com Tailscale para acesso privado ao Terminal e backup noturno.
- **Portabilidade é requisito:** código no GitHub privado, dados com backup, script de migração. Migrar de host < 1 hora.

## Custos
- Tudo gratuito: Gemini e Groq em camada gratuita, dados públicos, Tailscale pessoal, host gratuito.
- Nunca adicionar dependência paga sem perguntar. Redes sociais: **sem X/Twitter** (decisão do Rickson).

## Cérebro trocável
Toda chamada a LLM no código próprio passa por `quiron/nucleo/cerebro.py` (LiteLLM): Gemini grátis → Groq grátis → futuro Claude.
Trocar de modelo = mudar o `.env`.

## Como o Quíron trabalha em análises
- Rigor de CFA/CFP/FRM: premissas explícitas, fontes e datas, cenários e sensibilidade, limitações declaradas.
- **Números sempre calculados em Python com fonte identificada.** O modelo interpreta e redige; nunca inventa dado.
- Modos: entregar pronto, debater ou contestar (advogado do diabo), conforme o pedido; diz qual usou.
- Análises pesadas: resumo + relatório PDF (+ planilha), arquivados e visíveis no Terminal.
- Postura: colega sênior direto e franco, sem bajulação.

## Privacidade e compliance (obrigatório)
- Com modelo em camada gratuita, os dados podem ser usados pelo provedor: **nunca** enviar dado identificável de cliente.
  Clientes são `CLI-XXX`. **Decisão do Rickson (03/10/2026): não haverá anonimizador** — ele não digita dados
  identificáveis de clientes; a regra é de convenção. Não recriar o anonimizador sem ele pedir.
- Mapa código → nome real só na versão offline, criptografado. LGPD: `/esquecer <cliente>` apaga tudo.
- O Quíron não fala com clientes. Textos para clientes saem como RASCUNHO. Conteúdo público com lembrete de disclaimer.
- Análises de ações/emissores com recomendação são **uso interno e de estudo** (relatório de análise para terceiros é
  exclusivo de CNPI, Resolução CVM 20). Rodapé: "Uso interno — não constitui relatório de análise".
- Regras tributárias, FGC, alíquotas, ITCMD em `config/regras_mercado.yaml` com `verificado_em`; avisar após 90 dias.
- Coleta web: APIs oficiais e RSS sempre que existirem; respeitar termos de uso e robots.txt; nunca contornar paywall,
  login, captcha ou limites.

## Biblioteca e material
Livros e material de certificação são do Rickson, para uso pessoal. Citar livro/capítulo/página; não reproduzir trechos longos.
Arquivos com DRM não são processados.

## Stack
- Python 3.12, `uv`, SDK oficial de MCP para Python **v2** (`from mcp.server.mcpserver import MCPServer`; o antigo `FastMCP` não existe mais).
- Biblioteca: `pymupdf`, `ocrmypdf`/`tesseract` (por+eng), `ebooklib`, `chromadb`. Embeddings com `fastembed` (ONNX, sem
  PyTorch — leve para 8 GB): `paraphrase-multilingual-MiniLM-L12-v2` no PC; no host pode trocar por um mais robusto
  (`QUIRON_MODELO_EMBEDDINGS`). `QUIRON_EMBEDDINGS=lexico` = plano B sem download (usado nos testes).
- Biblioteca (código): lógica em `quiron/servicos/biblioteca/` (extração → trechos → embeddings → índice/catálogo →
  fichas/relatório; `consultas.py` formata as respostas); MCP fino em `quiron/mcp/biblioteca/`. As ferramentas devolvem
  trechos com citação; quem redige é o agente, seguindo `agente/skills/` (espelhadas em `.claude/skills/` para o Claude Code).
- Dados: Banco Central (SGS, Focus), Tesouro Transparente, ANBIMA (ETTJ), CVM Dados Abertos, IBGE, brapi, `yfinance`,
  datasets do Damodaran, RSS de notícias, Bluesky, Reddit e YouTube pelas APIs oficiais.
- Mercado (código): `quiron/servicos/mercado/` — `http.py` (httpx + cache SQLite em `dados/quiron.db`; fonte fora do ar
  devolve o último valor marcado DESATUALIZADO), um módulo por fonte (`bcb`, `tesouro`, `curva` (ANBIMA, plano B Tesouro),
  `cotacoes` (brapi/yfinance), `abertos` (CVM, IBGE, Damodaran)) e `painel.py` (Markdown com `📊 Fonte — horário`).
  Testes com respostas gravadas (`testes/gravacoes_mercado.py`); `testes/test_mercado_online.py` confere as fontes reais.
  Eventos sem API (Copom, resultados) em `config/agenda_fixa.yaml`.
  SGS: `api.bcb.gov.br` recusa conexões de fora do Brasil (ex.: nuvem) → plano B automático pelo web service SOAP
  oficial (`www3.bcb.gov.br/wssgs`). Focus (OData): espaços na URL precisam ser `%20` (com `+` dá erro 400).
- Notícias (código): `quiron/servicos/noticias/` — `coleta.py` (RSS/feeds oficiais de `config/fontes_noticias.yaml`, cache
  HTTP de 10 min, tabela `noticias` em `dados/quiron.db`, deduplicação por link canônico e por manchete), `classificacao.py`
  (temas, tickers, alertas e empresas por regras em `config/temas_noticias.yaml`; nome de empresa exige maiúscula e tem
  exceções, ex.: "Vale a pena"), `sentimento.py` (léxico pt/en com radicais e negação — indicação, não leitura fina),
  `redes.py` (Bluesky senha de app, Reddit OAuth "script", YouTube Data API; sem chave devolve o passo a passo) e
  `consultas.py`. MCP `quiron-noticias`. Sem RSS oficial: Reuters, Tesouro, ANBIMA, B3 (não raspar páginas).
- Terminal (código): `quiron/terminal/backend/` — `dados.py` (JSON a partir dos mesmos serviços; `TOPICOS` = função +
  intervalo; fontes lentas como o Tesouro vêm em segundo plano com resultado `parcial`), `app.py` (FastAPI: `/api/topico/*`,
  `/api/calc/*`, `/api/layouts`, `/ws` com assinatura por painel e memo compartilhado válido por 80% do intervalo; só
  127.0.0.1 por padrão; `TERMINAL_SENHA` ativa login por cookie). Frontend sem build em `quiron/terminal/frontend/`
  (JS puro + lightweight-charts 4.2 local em `vendor/`). Calculadoras em `quiron/servicos/calculadoras.py` (Python, com
  memória de cálculo). Cores: séries azul/laranja/aqua da paleta validada; alta/queda sempre com ▲/▼. Datas sem fuso:
  hora do sistema (consultas) ou de Brasília (agenda) — ver `_iso`. Aceite no navegador: `testes/test_terminal_navegador.py`.
- Agente (Fase 5, código em `quiron/runtime/`): `workspace.py` (cérebro em Markdown: modelos em `agente/workspace/`,
  cópia viva em `dados/workspace/` — SOUL gerado da persona, USUARIO, MEMORIA, ROTINAS, diario/; comandos de barra em
  `agente/comandos/*.md`), `memoria.py` (conversas em `dados/conversas.db` com FTS5, resumo/compactação), `agendador.py`
  (lembretes/tarefas com recorrências legíveis — uma vez, diario, dias_uteis, semanal, mensal — e limite de mensagens
  automáticas/dia da persona), `permissoes.py` (livre/confirmar/bloqueado por ferramenta em `config/agente.yaml`,
  aprovações por botão, hooks de compliance RASCUNHO e rodapé de uso interno), `ferramentas_internas.py`
  (ler_skill, lembrar, esquecer, buscar_conversas, agendar, listar/cancelar, propor_skill) e `batimento.py` (heartbeat que
  confere ROTINAS.md e só fala se valer a pena). Peças anteriores: `ferramentas_mcp.py` (cliente MCP dos servidores do `.mcp.json`;
  nomes `servidor__ferramenta` com `_`), `agente.py` (laço: persona + índice de skills + `ler_skill` + ferramentas MCP +
  `cerebro.conversar`, até 8 passos; `quiron-agente -q`), `telegram_bot.py` (bot próprio, long polling, lista branca,
  memória em `dados/conversas.db`), `hermes.py` (gera um HERMES_HOME próprio em `dados/hermes/` com SOUL.md, skills,
  MCP e toolsets perigosos desligados) e `comparativo.py` (10 pedidos, conferências de compliance, relatório em
  `dados/comparativo/`). `cerebro.conversar` devolve a mensagem original do provedor (assinaturas de pensamento do Gemini 3).
- Análise: `pandas`, `numpy`, `scipy`, `statsmodels`, `riskfolio-lib`/`PyPortfolioOpt`, `numpy-financial`.
- Relatórios: Markdown → PDF (`weasyprint`), `matplotlib`, `openpyxl`.
- Terminal: FastAPI + WebSocket + frontend leve, gráficos lightweight-charts/ECharts. Banco: SQLite.

## Estrutura de pastas
```
quiron/
  nucleo/        cerebro.py, config.py, regras.py, persona.py
  mcp/           biblioteca/, academia/, mercado/, noticias/, analise/, assessoria/, carreira/
  servicos/      lógica compartilhada entre MCP e Terminal
  terminal/      backend/ (FastAPI), frontend/
agente/
  skills/        instruções em Markdown, neutras de runtime (briefing, dossiê, valuation, compliance…)
  persona.md     gerado de config/persona.yaml
  runtime/       adaptador do runtime escolhido na Fase 5
biblioteca/      entrada/, texto/, fichas/, indice/
academia/material/
config/          persona.yaml, regras_mercado.yaml, guia_22_blocos.yaml, trilha_certificacoes.yaml,
                 fontes_noticias.yaml, watchlist.yaml
dados/           quiron.db, relatorios/, backups/
deploy/          docker-compose.yml, Dockerfiles, scripts (preparar host, backup, restaurar, migrar)
.mcp.json        registra os MCP do Quíron no Claude Code (desenvolvimento)
testes/
docs/
```

## Ordem de trabalho
Siga SEMPRE o `docs/00-ROTEIRO.md`: uma fase por vez, item por item, só avance após o teste de aceite.
Ao concluir itens, marque-os no roteiro e explique ao Rickson, em até 5 linhas, o que ficou pronto e como testar.

## Convenções
- Testes: `uv run pytest` (rápidos, sem internet). Os que usam chave/internet são marcados `@pytest.mark.online`
  e rodam com `uv run pytest -m online`. O teste do MCP sobe o servidor de verdade pelo `.mcp.json`.
- `agente/persona.md` é gerado: edite `config/persona.yaml` e rode `uv run quiron-gerar-persona`.
- Código e comentários em português. Toda funcionalidade com teste em `testes/`.
- Respostas com fonte: `📚 Livro — Autor, cap. X` ou `📊 Fonte — horário`.
- Cuidado com a RAM do PC (8 GB) nas Fases 0–4: processos leves, sem carregar modelos grandes.

## Nunca faça
- Nunca commitar `.env`, `segredos/`, `dados/`, `biblioteca/`, `academia/material/`.
- Nunca abrir portas públicas além da 22 no host. O Terminal é acessado pelo Tailscale.
- Nunca remover DRM, contornar limites/paywalls ou usar múltiplas contas para burlar cotas.
- Nunca executar operações financeiras reais nem acessar sistemas de corretora ou da EQI.
