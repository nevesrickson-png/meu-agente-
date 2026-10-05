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
  `quiron-sistema` (ping e status — Fase 0), `quiron-biblioteca`, `quiron-academia`, `quiron-mercado`, `quiron-noticias`, `quiron-analise`, `quiron-assessoria`, `quiron-organizacao`, `quiron-carreira`, `quiron-conteudo`.
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
Trocar de modelo = mudar o `.env`. Ordem: `LLM_PRINCIPAL` → `LLM_ALTERNATIVOS` (fila de Gemini grátis, cada um com cota
diária própria — o Flash mais novo só dá ~20 pedidos/dia) → `LLM_RESERVA`. Modelo com cota esgotada (429) fica em pausa até
a cota voltar (`_PAUSA`). `Config.ordem` troca a ordem pontualmente (ex.: gerador da Academia começa pelo Groq).

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
  Terminal v2 (Fase 12): tópicos `fa`/`fundos`/`plano`/`academia`/`tarefas`/`alertas`; ações em `app.py` (`/api/analisar`
  → mesma fila do Telegram com origem `terminal`, que o Terminal também processa; `/api/carteira/ler`, `/api/alertas`,
  `/api/tarefas`, `/api/chat` com o mesmo `Agente` + MCP abertos uma vez, conversa `CHAT_TERMINAL = -12`). Toda escrita
  passa por `_proteger` (cabeçalho `X-Quiron: terminal` e, sem senha, host local ou `.ts.net`). Frontend: `executarV2`
  (`TICKER FA|DCF`, `FUND`, `CMPF`, `PORT`, `PLAN`, `ACAD`, `TASK`, `ALRT`, `CHAT`), layout "Assessoria", manifest para o
  celular. Alertas em `quiron/servicos/alertas.py` (`dados/alertas.json`; avisa uma vez por disparo; o bot avalia a cada
  5 min em `laco_alertas`; MCP `criar_alerta`/`listar_alertas`/`remover_alerta`; comando `/alerta`).
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
  Comandos com `skill:` no frontmatter pré-carregam a skill (`responder(..., skills=[...])`); `audio.py` transcreve voz pelo
  Whisper do Groq (`whisper-large-v3-turbo`, pt, vocabulário de mercado); `rotinas_padrao` de `config/agente.yaml` são
  criadas uma vez (briefing 7h30) e o bot pré-aquece as fontes às 7h10.
- Memória persistente (`quiron/runtime/memoria_longa.py`, `dados/memoria.db`, 05/10/2026): camadas trabalho
  (`memoria.py`, limite duro de 40 msgs) → fatos (categoria, importância 1–5, origem dito/extraido/editado/importado,
  ativo/substituído; dedupe por texto normalizado ou similaridade ≥ 0,93; recusa dado pessoal em Python) → episódios
  (permanentes, FTS5 + vetor) → eventos dos comandos diretos (120 dias). `Escriba` (modelo começa pelo Groq via
  `config_escriba`): fecha episódio (30 min ocioso, 40 msgs, `/novo`) com título/resumo/pendências + operações
  adicionar/atualizar/apagar sobre os fatos existentes (estilo Mem0; apagar nunca remove fato "dito"); pistas ("prefiro",
  "a partir de agora"…) disparam extração da troca; "lembre que…" guarda na hora sem modelo. `contexto(pergunta)` entra
  no prompt: núcleo (importância ≥ 4) + relevantes (0,55 significado + 0,25 BM25 + importância + recência) + episódios +
  eventos 48 h. Embeddings da biblioteca (Lexico se o modelo não estiver baixado; `revetorizar`). `consolidar` às 3h no
  `laco_memoria` (junta repetidos, arquiva importância ≤ 2 sem uso há 120 dias). `MEMORIA.md` é espelho editável
  (`importar_edicoes_md` por hash; migra o formato antigo). Agente: `em_segundo_plano` (escriba em thread),
  `fechar_se_ocioso`, `novo_assunto`; Workspace.fatos/lembrar/esquecer delegam aqui; LGPD `apagar_por_cliente`. Bot:
  `/memoria` (conversas, buscar, esquecer, mudar, consolidar), `/lembrar`, eventos em `_registrar_evento`.
  Testes: `testes/test_memoria_longa.py`.
- Configurações (`quiron/configurador/`): regras do `.env` (`CAMPOS`, `salvar_valores`, `atualizar_env` preservando
  comentários, testes de chave, descobrir ID pelo getUpdates; segredos nunca voltam inteiros). `quiron-configurar` (tela
  avulsa em 127.0.0.1:8766) e `--verificar` (0 = completo) continuam existindo, mas o PC usa a interface única abaixo.
- Interface única (`uv run quiron` = atalho Quiron): `quiron/iniciar.py` (lançador: sobe o Terminal com `--central`,
  religa em 30 s se cair, código 3 = troca de modo lida de `dados/modo_proximo`, `QUIRON_CENTRAL=1`; se já aberto só abre
  o navegador) + `terminal/backend/central.py` (rotas `/api/sistema/*`: `Supervisor` do bot como processo filho
  `python -m quiron.runtime.telegram_bot` com registro em `dados/logs/telegram.log`, recusa segundo bot e encerra órfãos;
  chaves (salvar aplica no `os.environ` e reinicia o bot); Google Agenda (credencial por upload, `autorizar(abrir=…)`);
  verificação offline e troca de modo (sair força `os._exit` após 5 s); início automático do Windows; versão).
  Rotas de sistema: `_proteger` + cliente local (ou com TERMINAL_SENHA). Frontend: `nav.js`/`nav.css` (abas
  TERMINAL · ACERVO · CONFIGURAÇÕES + selo do Telegram) em `index.html`, `acervo.html` e `config.html`. Sem `--central`
  (Docker) o bot aparece como "gerenciado pelo servidor". `.bat` restantes: `Abrir Quiron.bat`, `Quiron Offline.bat`
  (`quiron --offline`) e `Quiron Telegram.bat` (só compatibilidade com o Abrir antigo). Testes: `testes/test_central.py`.
  `verificar_tudo` (POST `/api/sistema/verificar`, botão "Verificar tudo"): chaves, testes de rede, bot, servidores MCP,
  disco, memória, pasta de dados, regras sem conferência, Google. Supervisor: 3 quedas em < 60 s = situação "erro" com
  `motivo_da_queda` (token recusado, conflito, sem rede…) e espera de 5 min; lançador para após 3 quedas rápidas e
  avisa porta ocupada.
- Bot (depuração 05/10/2026): erro inesperado vira resposta amigável; `drop_pending_updates=False` + ignora mensagens
  com mais de 6 h; menu "/" via `set_my_commands` (`menu_telegram`); `/start` curto; comando errado sugere o parecido;
  sub-bots não cortam texto (o envio divide). Modos que capturam mensagens (treino, entrevista, `/pos`): um fecha o
  outro (`_preparar_modo`), `/sair` fecha todos, 3 h parados encerram sozinhos (`_expirar_modos`), falha da IA ao
  começar não deixa sessão aberta (`abandonar`). Datas: "próxima sexta", "meio-dia", `datas.relativo` ("daqui a 2
  horas"). Calculadora CDB × LCI aplica `aliquota_iof` (< 30 dias). Google Agenda bloqueado no offline.
- Áreas (`quiron/servicos/areas.py`): 20 campos em `config/areas_conhecimento.yaml` + certificações da trilha (+ CEA) +
  personalizadas em `dados/areas_personalizadas.yaml` (fora do git). Cada área = pasta do acervo (id minúsculo) + trilha da
  Academia (programa em `config/editais/<ID>.yaml`; campos têm `tipo: campo`; sem arquivo → programa provisório de 1 tópico).
  `areas.reconhecer('renda fixa duration')` acha a área no início do texto.
- Acervo (`quiron/servicos/acervo.py` + Terminal `/acervo`, `acervo.html`): upload em partes (PUT com corpo bruto, limite
  300 MB, só PDF/EPUB, nunca sobrescreve) para `biblioteca/acervo/<área>/`; fila em `dados/acervo.db` com um processador em
  segundo plano (`ingerir_arquivo(..., area=)`); trechos guardam `area` (filtro em `Indice.buscar(area=)` e nos MCP da
  biblioteca); mover/remover; escrita exige cabeçalho `X-Quiron: acervo` e, sem senha, host local ou `.ts.net`.
- Academia (Fase 6, `quiron/servicos/academia/`, multiárea — `cert` = id da área): `edital.py` (PDF oficial → `config/editais/CFP.yaml`, 8 módulos/pesos/922
  tópicos; códigos de tópico são a referência de tudo), `banco.py` (`dados/academia.db`: questões, respostas, flashcards,
  simulados, preferências; SM-2 para cards e para questões erradas), `gerador.py` (gera no Groq → `validar` (estrutura +
  `verificacao` aritmética calculada sem eval) → `revisar` por modelo de OUTRO provedor, que resolve sozinho e confere
  coerência; recusadas não entram), `diagnostico.py` (acerto suavizado (a+1)/(n+2), prontidão ponderada pelo peso, plano em
  blocos de 30 min), `estudo.py` (Filtro módulo/tópico/tema, simulados 16/40/140 por peso, geração noturna
  `config/academia/geracao.yaml`, banco inicial `config/academia/banco_inicial_cfp.json`), `consultas.py` + MCP
  `quiron-academia`, `cli.py` (`quiron-academia`). Telegram: `runtime/academia_bot.py` (direto, sem LLM; botões `ac:*`; `/area` troca a área ativa, guardada em
  `preferencias.area_ativa`; filtro nos botões `ÁREA|m3`).
  `/aula` e `/caso` usam as skills `academia-aula`/`academia-caso`. Catálogo de gratuitos: `config/materiais_gratuitos.yaml`.
- Análise (Fase 7, `quiron/servicos/analise/`): `relatorio.py` (modelo único Relatorio → PDF via `pymupdf.Story` em blocos
  — gráfico com altura fixa nunca encolhe, passa de página; sem fundo colorido em CSS (o Story repete fundos na página
  seguinte); rodapé/cabeçalho carimbados em Latin-1 — + planilha openpyxl + Markdown + JSON), `fila.py` (`dados/analise.db`,
  `@tipo`, reserva atômica, `dono`=PID e `recuperar_orfas`, FTS5, `a_entregar`/`marcar_entregue`), `redacao.py` (modos;
  `conferir` números do texto contra fatos/tabelas/diferenças; 2ª tentativa e aviso), `tipos/` (renda_fixa:
  cenário mensal Selic→Focus interpolada, IPCA Focus, IR regressivo, custódia `tesouro_direto` das regras, sensibilidade).
  MCP `quiron-analise` (processa a fila em segundo plano; origem = `QUIRON_ORIGEM`, o bot define `telegram` e entrega
  resumo + PDF + planilha em `laco_analises`). Calculadoras: `ESQUEMAS` + `executar()` em `calculadoras.py` (fonte única
  do Terminal `/api/calc`, do MCP e do `/calc`). Terminal: `RPT` (`/api/relatorios`, `/relatorios/<id>/<arquivo>`).
  Decisão 04/10/2026: PDF com pymupdf em vez de weasyprint (weasyprint exige GTK no Windows).
  Gráficos: `barras_h` (1 série ou agrupadas, aceita negativos), `linhas`, `dispersao` (campo `x` por série).
- Carteira (Fase 8, `quiron/servicos/carteira/`): `modelo.py` (8 classes com proxy e duration, `Posicao`, `Carteira`,
  perfis de `config/alocacao_perfis.yaml`), `leitura.py` (texto pelo cérebro com plano B por regras, planilha, print por
  OCR local; `mascarar_identificadores` antes do modelo; ticker extraído do nome), `arquivo.py` (`dados/carteiras/CART-*.json`
  — o agente passa só o id), `series.py` (mensais: SGS 4391/433, índices sintéticos PRE3/IPCA7 do histórico do Tesouro,
  Yahoo ajustado com filtro de salto >60%, cesta de FII, MULTI = 70% CDI + 30% IBOV; cache 12 h em `dados/cache_series`),
  `risco.py`, `stress.py` (`config/cenarios_stress.yaml`; renda fixa por duration modificada, ações por beta, pós-fixado
  com efeito em 12 meses), `otimizacao.py` (Focus + Tesouro do dia, premissas de `config/premissas_carteira.yaml`, SLSQP
  nas faixas do perfil), `rebalanceamento.py` (IR por tipo, isenção de R$ 20 mil, `aporte_sem_vender`) e `backtest.py`.
  Tipo `carteira_diagnostico` em `analise/tipos/carteira.py`; MCP `ler_carteira`; bot lê foto/planilha (`tratar_arquivo`)
  e comando `/carteira`. Testes offline com séries sintéticas em `testes/test_carteira.py`.
- Planejamento (Fase 9, `quiron/servicos/planejamento/`): `ficha.py` (Ficha por CLI-XXX em `dados/fichas/`, mescla,
  histórico, `validar` → pendências), `impostos.py` (IRPF mensal/anual com redução de 2026, imposto mínimo de alta renda,
  INSS, Simples III/V, Presumido — tabelas em `regras_mercado.yaml`), `diagnostico.py` (renda líquida, fluxo, balanço,
  indicadores, objetivos; `vf`/`pmt_para`/`vp_renda`), `aposentadoria.py` (capital com INSS, aporte médio, Monte Carlo
  lognormal com bissecção para 85%, renda sustentável, aporte viável), `sucessao.py`, `tributario.py`, `protecao.py`,
  `empresario.py` e `plano.py` (orçamento de aportes + plano de ação). Premissas em `config/premissas_planejamento.yaml`.
  Tipos `planejamento_completo`, `aposentadoria`, `sucessao`, `tributario`, `protecao`, `empresario` em
  `analise/tipos/planejamento.py` (rodapé de RASCUNHO para revisão). MCP `quiron-assessoria` (ficha + `esquecer_cliente`,
  que pede confirmação); `servicos/lgpd.py` apaga ficha, carteiras, relatórios, conversas e memória que citam o código
  (código inteiro: CLI-01 não apaga CLI-012). Skill `agente/skills/planejamento.md`; comandos /cliente, /planejamento,
  /aposentadoria, /sucessao, /tributario, /protecao, /empresario, /esquecer.
- Fundos (Fase 10, `quiron/servicos/fundos/`): `cvm.py` (CVM Dados Abertos → `dados/fundos.db`: cadastro CVM 175
  (classes, fundos/gestor, subclasses; 7 dias), extrato (taxas, prazos), índice MENSAL de todos os fundos a partir do
  informe diário (cada mês baixado uma vez, zip descartado; mês corrente e anterior renovados a cada 12 h; desde 2021-01),
  FII (informe mensal; ISIN → ticker; ISIN repetido → o de mais cotistas), busca, pares por classificação ANBIMA) e
  `metricas.py` (janelas até o último mês fechado, risco mensal, percentil entre pares com PL ≥ R$ 10 mi). Tipos
  `fundo_analise`, `fundos_comparativo`, `gestora`, `previdencia_portabilidade`, `fii_comparativo` em
  `analise/tipos/fundos.py` (tabela de conferência com as cotas da CVM; DY de FII pelos proventos pagos via Yahoo).
  MCP `quiron-mercado`: `buscar_fundo`, `buscar_gestora`, `fii_dados`. Skill `agente/skills/fundos.md`; comandos
  /fundo, /comparar_fundos, /gestor, /previdencia, /fii, /alternativos. Aceite online em `testes/test_fundos_online.py`.
- Valuation (Fase 11, `quiron/servicos/valuation/`, USO INTERNO): `cvm_cias.py` (zips DFP/ITR/FCA em `dados/cache_cvm/`;
  contas pelo código do plano padronizado da CVM + depreciação/capex/arrendamentos/minoritários pelo nome dentro do grupo,
  sem somar pai e filho; consolidado com plano B individual; versão mais recente; LTM = ano + YTD − YTD anterior; ações da
  composição do capital; tickers/setor do FCA) e `dcf.py` (WACC em US$ → R$ por paridade de inflação: ^TNX + β de setor
  Damodaran realavancado × ERP madura + risco-país; Kd por rating sintético; IR efetivo histórico; projeção de 10 anos com
  fade até g = IPCA LP + real; perpetuidade com reinvestimento g ÷ ROIC; cenários, sensibilidade, DCF reverso e WACC
  implícito). Tipos `valuation_dcf` (pontos de debate calculados; β de regressão como visão alternativa; tese),
  `setor_multiplos` (corrige ações informadas em milhares), `resultado_trimestral` em `analise/tipos/valuation.py`, todos
  com rodapé "Uso interno — não constitui relatório de análise (Resolução CVM 20)". Financeiras: sem DCF da firma.
  MCP `quiron-mercado` `buscar_empresa`; skill `agente/skills/valuation.md`; comandos /empresa, /valuation, /tese,
  /setor, /resultado; premissas em `config/valuation.yaml`; aceite online em `testes/test_valuation_online.py`.
- Assessoria (Fase 13, `quiron/servicos/assessoria/`): `datas.py` (expressões ditas → data em Python; o modelo só copia
  a expressão), `compliance.py` (regras de promessa/risco/certeza/rentabilidade passada/FGC/pressão + dados pessoais;
  ignora negação), `pos_reuniao.py` (transcrição mascarada → JSON do cérebro ou plano B por regras → tarefas viram
  lembretes `[CLI-XXX]` (sem prazo dito = 2 dias úteis), próximo contato, sugestões de ficha só de campos simples
  validados e aplicadas com confirmação; `dados/reunioes/<CLI>/`), `treino.py` (`config/treino.yaml`; `dados/treino.db`;
  cliente via `cerebro.conversar`; feedback = métricas Python + rubrica do modelo, nota ponderada aqui, compliance ≤ 3
  com alerta grave), `objecoes.py` (`config/objecoes.yaml`), `vencimentos.py` (carteira mais recente por cliente) e
  `dossie.py`. MCP `quiron-assessoria` ganhou dossie_reuniao, registrar_pos_reuniao, aplicar_reuniao_na_ficha
  (confirmar), reunioes_do_cliente, objecoes, conferir_compliance, vencimentos e as ferramentas de treino. Telegram:
  `runtime/assessoria_bot.py` (direto, sem LLM no laço: `/pos` espera o próximo áudio/texto; treino ativo captura as
  mensagens; botões `as:*`). Skill `agente/skills/assessoria.md`; comandos /reuniao, /objecao, /explicar, /mensagem,
  /vencimentos. `lgpd.py` apaga também reuniões e lembretes. Aceite online em `testes/test_assessoria_online.py`.
- Organização (Fase 14, `quiron/servicos/organizacao/`): `banco.py` (`dados/organizacao.db`: tarefas, notas + FTS5,
  metas e registros), `tarefas.py` (frase → `datas.extrair` (texto limpo + data + hora, em Python) → tarefa; com hora =
  lembrete na hora, só data = 8h, sem data = lista; lembrete é agendamento `[T<id>] …` do `Agendador`; adiar recria o
  lembrete; `por_lembrete`), `notas.py`, `metas.py` (semanal/mensal/total com prazo; ritmo esperado calculado),
  `hoje.py` (`montar_hoje`, `montar_revisao` — sem modelo) e `google_agenda.py` (Calendar v3 por httpx, OAuth loopback +
  PKCE sem bibliotecas extras; `segredos/google_oauth.json` + `google_token.json`, renovação automática; escopo só
  `calendar.events`; `quiron-google autorizar [--sem-navegador]`; guia `docs/09-GOOGLE-AGENDA.md`; `.bat`). MCP
  `quiron-organizacao` (criar/listar/concluir/adiar/remover tarefa, hoje, revisão, notas, metas, agenda, evento).
  Telegram: `runtime/organizacao_bot.py` (direto: /tarefa /tarefas /feito /adiar /hoje /nota /notas /meta /metas
  /revisao /evento; botões `or:*`); `agenda_vencida` devolve `Saida` (lembrete de tarefa com botões; rotina que começa
  com "/" roda pelo `tratar`, ex.: `/revisao` domingo 18h em `rotinas_padrao`). `agendar` interno = rotinas; tarefa
  pontual = `criar_tarefa`. Terminal: TASK com "Tarefa rápida" (`/api/organizacao/tarefa`). LGPD apaga tarefas/notas.
  `segredos/` entra no volume do Docker e no backup. Aceite online em `testes/test_organizacao_online.py`.
- Carreira (Fase 15, `quiron/servicos/carreira/`, `dados/carreira.db`): `radar.py` (`config/radar_regulatorio.yaml`:
  RSS do gov.br (CVM, Receita) filtrados por palavras de norma, API pública da busca de normativos do BCB (só tipos de
  norma), API da Câmara (PL/PLP/PEC/MPV recentes); relevância = peso do tema (palavra no início de palavra; ≤ 4 letras =
  palavra inteira); sem repetir link; `novidades` marca vistos; avisa regras_mercado sem conferência), `diario.py` (modelo
  só estrutura; plano B por regras; horizonte em data em Python; preço do dia e do Ibovespa; lembrete `[D<id>]`; `medir`
  retorno/excesso/a favor; Brier e faixas de confiança), `plano.py` (`config/carreira.yaml`; data de prova também na
  Academia), `portfolio.py` (exclui tipos de cliente e CLI-XXX; PDF via Relatorio), `entrevista.py`
  (`config/entrevista.yaml`; mesma mecânica do treino). MCP `quiron-carreira`; Telegram `runtime/carreira_bot.py`
  (/carreira /diario /portfolio /entrevista /radar; entrevista ativa captura mensagens; `Saida.arquivo` manda o PDF);
  rotina `/radar novidades` segunda 8h20; teses a revisar entram no `/revisao`. Skill `agente/skills/carreira.md`.
  Aceite online em `testes/test_carreira_online.py`.
- Offline (Fase 16): `quiron/nucleo/offline.py` (`QUIRON_MODO=offline`; `config/offline.yaml`): `carregar_config` só
  com o modelo local (`ollama_chat/qwen2.5:3b`, `api_base` + `num_ctx` no cérebro), `http.obter` nunca vai à rede (cache
  marcado desatualizado), Yahoo recusa, `ConexaoMCP` só carrega os servidores/ferramentas listados e corta parâmetros
  opcionais (`_enxuto`), agente com `PROMPT_OFFLINE` curto, sem internas, 5 passos (com 33 ferramentas o 3B errava).
  `quiron/servicos/offline/`: `cofre.py` (mapa CLI-XXX → nome/contatos em `cofre/clientes.cofre`, Scrypt n=2^15 +
  Fernet, troca atômica; abre só offline e sem modelo de nuvem; nunca entra em ferramenta do agente nem no pacote),
  `pacote.py` (tar.gz com índice, embeddings e dados; SQLite pela API de backup; importação guarda o anterior em
  `dados/antes-da-importacao-*`; bloqueia caminhos fora de dados/biblioteca), `cli.py` (`quiron-offline verificar |
  pacote | importar | baixar | cofre …`). Terminal: `/api/modo`, `/api/biblioteca` (BIB), `/api/cofre/*` (CLI; só
  offline + 127.0.0.1 + cabeçalho; sessão fecha em 15 min), `/api/offline/pacote` (exige TERMINAL_SENHA); selo OFFLINE
  e layout "Offline". `Quiron Offline.bat` (UV_OFFLINE, sobe o Ollama, verifica, abre). LGPD avisa para remover do
  cofre. Guia `docs/10-OFFLINE.md`; aceite em `testes/test_offline_aceite.py` (precisa do Ollama).
- Conteúdo (Fase 17, `quiron/servicos/conteudo/`, `config/conteudo.yaml`): `insumos.py` (fatos numerados com crédito:
  SGS/Focus, regras de `regras_mercado.yaml` com contas em Python — poupança, IR regressivo, FGC, conta Tesouro Selic
  líquido × poupança —, radar, notícias (link do redirect desembrulhado), agenda, biblioteca; aviso de regra não
  conferida fica só nas notas internas), `gerador.py` (pautas com fatos validados ou plano B por regras; peça por formato
  com até 2 tentativas — reescreve se houver alerta grave ou número sem fonte; salva em `dados/conteudo/` e no banco),
  `revisao.py` (tira marcas [n], quebra slides/posts, compliance, números com %/R$/decimal conferidos com os insumos,
  créditos do que foi citado, disclaimer + CVM 20 se ticker/empresa + IA, "RASCUNHO") e `ideias.py` (`dados/conteudo.db`
  com FTS5). MCP `quiron-conteudo`; Telegram `runtime/conteudo_bot.py` (/pauta /roteiro /fio /ideia /ideias /conferir).
  Skill `agente/skills/conteudo.md`. Aceite online em `testes/test_conteudo_online.py`.
- Deploy: `Dockerfile` (python:3.12-slim + uv + tesseract, usuário 1000), `docker-compose.yml` (serviços `agente` e
  `terminal`, porta só em 127.0.0.1:8765 e publicada pelo `tailscale serve`), `deploy/` (preparar_host, instalar,
  backup às 3h com rclone opcional, restaurar, migrar). Volumes: dados, biblioteca, config, agente, segredos.
- Análise: `pandas`, `numpy`, `scipy`, `statsmodels`, `riskfolio-lib`/`PyPortfolioOpt`, `numpy-financial`.
- Relatórios: PDF com `pymupdf` (Story), `matplotlib`, `openpyxl`, `markdown`.
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
