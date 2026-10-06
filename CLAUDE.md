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
  datasets do Damodaran, RSS de notícias (79 fontes, grupos brasil/global/asia/oficiais/setores_br/setores_global), Bluesky, Reddit e YouTube pelas APIs oficiais.
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
  memória de cálculo). Cores: tokens de `tema.css` (séries azul/laranja/aqua da paleta validada); alta/queda sempre com ▲/▼. Datas sem fuso:
  hora do sistema (consultas) ou de Brasília (agenda) — ver `_iso`. Aceite no navegador: `testes/test_terminal_navegador.py`.
  Terminal v2 (Fase 12): tópicos `fa`/`fundos`/`plano`/`academia`/`tarefas`/`alertas`; ações em `app.py` (`/api/analisar`
  → mesma fila do Telegram com origem `terminal`, que o Terminal também processa; `/api/carteira/ler`, `/api/alertas`,
  `/api/tarefas`, `/api/chat` com o mesmo `Agente` + MCP abertos uma vez, conversa `CHAT_TERMINAL = -12`). Toda escrita
  passa por `_proteger` (cabeçalho `X-Quiron: terminal` e, sem senha, host local ou `.ts.net`). Frontend: `executarV2`
  (`TICKER FA|DCF`, `FUND`, `CMPF`, `PORT`, `PLAN`, `ACAD`, `TASK`, `ALRT`, `CHAT`), layout "Assessoria", manifest para o
  celular. Alertas em `quiron/servicos/alertas.py` (`dados/alertas.json`; avisa uma vez por disparo; o bot avalia a cada
  5 min em `laco_alertas`; MCP `criar_alerta`/`listar_alertas`/`remover_alerta`; comando `/alerta`).
- Cartas de gestores (06/10/2026, `quiron/servicos/cartas/`, `dados/cartas.db`): `coleta.py` (fontes em
  `config/cartas_gestores.yaml`; `conferir` = robots.txt → página → feed da categoria (feed geral do site é ignorado) ou
  links com PDF/palavra + data (`extrair_data`, futuro ≤ hoje+5; `_NAO_CARTA` tira carta-consulta/assembleia/lâmina);
  situação ativa ≤ 120 dias; `atualizar` só as vencidas (20 h), 8 em paralelo; `ler_carta` só de domínio cadastrado ou
  link já listado, ≤ 15 MB) e `consultas.py` (textos). MCP `quiron-noticias` (`cartas_gestores`, `situacao_gestoras`,
  `ler_carta`); Terminal tópico `cartas` + `POST /api/cartas/atualizar` + painel CARTAS; bot `/cartas` (em
  `carreira_bot`) e `laco_cartas` de hora em hora. Guardamos só título/data/link.
- TV (06/10/2026, `quiron/servicos/tv.py` + `terminal/frontend/tv.html`, rota `/tv`): canais em `config/tv_canais.yaml`,
  os do Rickson em `dados/ajustes/tv_canais.yaml` (`meus`, `ocultos`); `resolver` (link/@/UC… pela Data API ou página
  pública), `videos` (só Data API; o RSS /feeds/videos.xml é proibido no robots.txt do YouTube → sem chave a tela toca
  `videoseries?list=UU…`), `ao_vivo`/`ao_vivo_varios` (página pública /channel/<id>/live: vídeo, título, quantos
  assistem; cache 3 min); tela "ao vivo primeiro" (modo auto: conferir antes de tocar, selo AO VIVO, canais no ar no
  topo, reconfere a cada 3 min). Rotas `/api/tv/*` (+ `/api/tv/ao_vivo`; escrita com `_proteger`).
- Resumo de mercado (06/10/2026, `quiron/servicos/mercado/resumo.py`): `coletar` (8 seções `SECOES`; `_linha` =
  `cotacoes.desempenho` sobre 1 ano do Yahoo, com `_dia_confiavel` contra os pregões do Ibovespa (o Yahoo pula/repete
  dias; câmbio do dia só pela PTAX); Tesouro com bps, Focus, agenda Copom/FOMC; manchetes por tema + `FILTRO_SECAO`)
  → `redigir` (uma chamada, max_tokens 8000 por causa do pensamento do Gemini 3; `_limpar` corta frase com número fora
  dos fatos/manchetes; sem IA = tópicos) → `Resumo.texto()` + PDF (Relatorio) em `dados/resumos/AAAA-MM-DD-HHMM/`.
  Bot `/resumo` (direto), rota "resumo de mercado", MCP `quiron-mercado.resumo_mercado`, Terminal `GET /api/resumo`,
  `POST /api/resumo/gerar`, `/resumos/<id>/relatorio.pdf`, painel RESUMO. `cotacoes.desempenho` + MCP `desempenho`
  (semana/mês/ano/12m/52 semanas).
- Correções do Telegram (06/10/2026): `relatorio.pdf` monta o PDF em memória (`DocumentWriter(BytesIO)` → `_carimbar`
  em bytes → `_gravar_arquivo` com novas tentativas; nada de `.tmp` + rename, que dava WinError 5); `fila.repetir` +
  `motivo_amigavel` (bot manda o motivo em português com botão `an:repetir:<id>`; falhas de PermissionError voltam à
  fila ao ligar o bot; MCP `repetir_analise`); `com_sugestoes` nunca deixa linhas "»" no texto; prompt: sem "Modo:" em
  confirmação de fila, não estimar número que não veio, conferir a fila antes de falar de análises.
- Perfil de empresa (06/10/2026, `quiron/servicos/valuation/perfil.py`): FCA (setor, descrição, sede, fundação,
  controle, site) + FRE (`posicao_acionaria` ≥ 5% sem CPF/CNPJ e sem cadeia societária, `participacao_sociedade`,
  `empregado_posicao_local`; última versão) + Yahoo `info` traduzido pelo cérebro; cache 7 dias em
  `dados/cache_cvm/perfis/`. `secao` abre `valuation_dcf` e `resultado_trimestral` (`_com_perfil`); MCP `perfil_empresa`.
- Imóveis de FII (06/10/2026, `quiron/servicos/fundos/fii_imoveis.py`): informe TRIMESTRAL da CVM (imovel, inquilino,
  ativo; último trimestre por fundo; tabelas `fii_imovel/fii_inquilino/fii_ativo` em `dados/fundos.db`, 1 download por
  semana); `local` tira cidade/UF do endereço; `carteira` (por UF, vacância ponderada pela área, setores, ativos por
  tipo); seções no `fii_comparativo`; MCP `fii_imoveis`.
- Depuração 06/10/2026 (`testes/test_revisao_bugs.py`): `agenda_vencida` roteia a rotina para "/comando" antes do
  `tratar` (texto livre seria capturado por /pos/treino/entrevista) e isola cada item em try; `laco_analises` marca
  entregue logo após o texto, anexo com falha avisa; re-tentativa de PermissionError uma vez na vida
  (`dados/analises_repostas.json`); fila: `dono` = máquina:PID, órfã só com dono morto (ou > 6 h), UPDATE final com
  `AND dono=?`; Terminal: `_host_permitido` (middleware, sem senha só 127.0.0.1/localhost/.ts.net) + `_origem_permitida`
  no `/ws` + `_proteger` nos layouts + 400 para parâmetro inválido; câmbio do dia em `cotacoes.yahoo` =
  `_variacao_contra_ptax`; `painel.texto_cotacao` em horário de Brasília; BCB: janela de 10 min só abre com recusa
  real; cartas: `casar_gestoras` sem acento, `atualizar(nomes=[])` não confere nada, `ler_carta` segue redirecionamento à
  mão só para endereço público, `_MES` com fronteira de palavra, data não se apaga; `vencidas()` antes de abrir thread.
- Depuração 2 (06/10/2026, `testes/test_revisao_bugs2.py`): `nucleo/trava.py` (`trava_arquivo` entre processos +
  `gravar_atomico`; usado em `alertas.json`, cuja avaliação consulta a rede fora da trava e mescla no fim);
  `impostos.ir_na_fonte(rendimento, deducoes)` (redução 2026 sobre o bruto; maior entre deduções e
  `desconto_simplificado_mensal`); `calculadoras._num` (ponto de milhar); `restaurar_copia` regrava o MEMORIA.md e
  reaplica `lgpd.esquecidos()`; `lgpd` limpa cópias/exportações/logs/metas/carreira/treino/conteúdo; `datas.RE_HORA`
  com período em todas as formas e "as" sem acento só com horas/período; `_origem_permitida` = mesma origem (ou
  localhost×127.0.0.1 na mesma porta); acervo publica com `os.link` (nunca sobrescreve) a partir de temporário único;
  OCR em cache por sha256; pacote offline extrai à parte e troca com desfazer; backup.sh em dois tars; Gemini PerDay
  pausa até a meia-noite do Pacífico; `.env` com aspas quando preciso, `utf-8-sig`, sem interpolação.
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
  Registro completo (append-only, tabela `registros` + FTS5, `synchronous=FULL`): `registrar(canal, chat, tipo, conteudo,
  meta)` — tipos entrada/resposta/ferramenta/ferramenta_resultado (agente, canal por `canal_de`), comando/resposta_comando
  (sub-bots, em `BotQuiron.tratar` quando não passa pelo agente), audio, arquivo, proativo (`registrar_proativo` nos
  laços), memoria_fato/memoria_episodio; migra `conversas.db` uma vez; `linha_do_tempo`, `buscar_registros` (também no
  `buscar_conversas`), `fazer_copia` (API de backup do SQLite, pasta por dia, 30 mantidas; `nome=` avulsa),
  `restaurar_copia` (guarda `antes-de-restaurar-*`), `verificar_integridade`, `exportar` (JSON). Cópia às 3h no
  `laco_memoria` + `central.copia_diaria_da_memoria` no modo central; "Verificar tudo" mostra a saúde da memória.
  CLI `quiron-memoria`. Bot: `/memoria hoje|DD/MM|estado|copia|exportar`. Postgres: não usado de propósito (um usuário,
  PC de 8 GB; SQLite é o mesmo modelo relacional sem servidor) — o esquema é simples de levar para Postgres no servidor.
- Simulador de patrimônio (`quiron/servicos/planejamento/simulador.py`, 05/10/2026; inspirado num reel de simulador de
  patrimônio): `Entrada` (R$ de hoje) → `simular` = 3 cenários (`simulador.cenarios_pp`) + Monte Carlo lognormal
  (`volatilidade_aa`, semente fixa) + respostas: aporte necessário (`pmt_para`), independência (1ª idade em que o
  patrimônio ≥ `capital_para_renda` = VP da renda até `expectativa_vida_plano` a `retorno_real_usufruto`, com chance),
  tempo até a meta (`meses_ate`), imóvel × financeiro (`imovel_x_financeiro`: aluguel líquido reinvestido, custos de
  compra/venda, valorização de empate por bissecção). `ler_frase` (regras, sem modelo), `de_ficha(CLI-XXX)`, `texto`,
  `grafico_png`. MCP `quiron-assessoria.simular_patrimonio`; Terminal `POST /api/simulador` + painel `SIM` (SVG próprio
  com dica, tabela, premissas); Telegram `/simular` (texto + PNG via `send_photo`). Testes `testes/test_simulador.py`.
- Interface do agente (05/10/2026): `para_html` (Markdown do modelo → HTML do Telegram, tudo escapado; tabelas em
  `<pre>` alinhado; envio com `parse_mode="HTML"` e plano B em texto simples), `/start` com `ATALHOS` (`qa:/…`), chat do
  Terminal com `textoChat` (títulos, listas, código, links seguros, tabelas).
- Fluidez (`quiron/runtime/roteamento.py`, 05/10/2026): `rotear(texto, ultima_tarefa)` (padrões de alta confiança,
  frase inteira, sem acento → `/comando args`; o bot chama antes da IA, depois dos modos de captura; texto >400 ou com
  quebra de linha vai para a IA; "passa para…"/"feito" usam a tarefa criada/mexida há < 30 min) e
  `selecionar_ferramentas` (internas sempre + ~32 MCP por área (`AREAS`) + IDF da descrição + citadas na skill carregada;
  `ler_skill` no meio do laço amplia o contexto). Trocas diretas entram em `agente.memoria` (continuidade). Progresso:
  `responder(..., progresso=)` → `Andamento` no `_rodar` ("⏳ Consultando …", `descrever_ferramenta`, apagada no fim).
  Sugestões: linhas finais "» …" (prompt) → `separar_sugestoes` → botões `ms:<id>` (`clicar_sugestao`); no Terminal,
  `separarSugestoes` + `.chat-sugestoes`. Testes `testes/test_fluidez.py`.
- Revisão crítica (05/10/2026, `testes/test_critico.py`): `agente.dados_identificaveis` barra CPF/telefone/e-mail antes
  da IA na nuvem (CNPJ liberado; offline não barra; não registra o texto); `ConexaoMCP.chamar` com
  `QUIRON_TIMEOUT_FERRAMENTA` (180 s) e o bot com `TEMPO_MAXIMO_RESPOSTA_S` (420 s); estado por mensagem em
  `ContextVar` (`_ESTADO`, `_marcar`); `procurar_ferramentas` (PROCURAR) libera ferramentas fora do recorte;
  `aplicar_compliance` põe o rodapé antes das linhas "» "; `ao_clicar` ignora quem não está em `permitidos`;
  confirmar em `config/agente.yaml` para remover_tarefa, criar_evento, remover_alerta, fechar_tese, cancelar_agendamento.
  Manual do usuário: `docs/12-MANUAL-DO-BOT.md` (atualizar quando surgir função nova).
- Informação (05/10/2026, `testes/test_informacao.py`): `noticias/relevancia.py` — `agrupar` (histórias: manchetes com
  ≥ 3 radicais em comum e ≥ 50%, ou ≥ 4 e ≥ 35%, em 36 h; principal = fonte de maior peso), `nota` (pesos de tema de
  `temas_noticias.yaml:pesos`, tema no título × 0,35 só no resumo; sem tema no título nem ativo/alerta/oficial = 0;
  `ruido` descarta; × peso da fonte (`fontes_noticias.yaml:peso`); × (1 + 0,6·log2 cobertura); meia-vida 12 h),
  `diversificar` (máx. por tema principal). `consultas.historias`/`linha_historia`; `top`, `noticias`, Terminal e
  conteúdo usam histórias. 24 fontes (redirecionador `*http` desembrulhado na coleta). Briefing em Python:
  `mercado/briefing.py` (`montar` → blocos fixos com ▲/▼, bps do Tesouro contra o pregão anterior, Focus em p.p., IBGE
  só `IBGE_IMPORTANTES`, notícias 18 h; `comentario` = 2–3 bullets da IA, linha com número fora do briefing é
  descartada; `completo`). /briefing sem argumentos e a rotina das 7h30 ("Faça meu briefing." via `rotear` em
  `agenda_vencida`) vão direto; o MCP `briefing` devolve o texto pronto. `skills_provaveis` pré-carrega a skill de
  notícias/briefing. Direto do bot com títulos em negrito (/hoje com próximos 3 dias e agenda econômica, /revisao,
  /radar com link curto, /academia sem a lista de campos).
- Visual (05/10/2026): sistema de design único em `terminal/frontend/tema.css` (tokens de cor/forma/tipografia, escuro
  padrão e `[data-tema="claro"]`; acento azul, verde/vermelho só para alta/queda com ▲/▼, números tabulares, cartões com
  raio 14 px, cabeçalho translúcido) + `tema.js` no `<head>` (aplica o tema salvo em `localStorage["quiron-tema"]` =
  auto/claro/escuro antes de desenhar). Todas as páginas (index, config, acervo, login) carregam os dois; `nav.js`
  coloca o selo do sistema (classes `s-ok/s-aviso/s-erro` — `aviso` já é o toast do Terminal) e o botão de tema em
  `#nav-extra` (ou depois das abas) e dispara `quiron:tema`; o `app.js` lê cores do tema via `COR` (getters de CSS) e
  redesenha os painéis na troca. Novo painel ocupa o primeiro espaço livre da grade (`proximaPosicao`).
- Preferências e revisão (05/10/2026, `testes/test_preferencias.py`): `config.ler_yaml` mescla `dados/ajustes/<nome>.yaml`
  por cima de `config/` (dicts recursivos; `com_ajustes=False` lê o padrão; ajuste corrompido é ignorado);
  `salvar_ajuste`/`escrever_ajuste`/`ler_ajuste`. `servicos/preferencias.py` (`ler`/`salvar`: watchlist validada e só o que
  difere do padrão, mensagens/dia, fontes `desligadas` (filtradas em `coleta.ler_fontes` e `coleta.listar`), briefing =
  uma rotina no agendador, `_marcar_briefing_configurado`) + rotas `GET/POST /api/sistema/preferencias` + seção
  Preferências em `config.html`. Rotinas padrão criadas uma vez na vida (`dados/rotinas_padrao_criadas.json`); rotina
  só vai direto pelo `rotear` se for leitura (`ROTINAS_DIRETAS`); pré-aquecimento 20 min antes da rotina do briefing.
  Desempenho: `coleta.coletar` baixa em paralelo (8), `tesouro._linhas` lê o CSV uma vez por download (memo + trava),
  `briefing.montar` busca os blocos em paralelo (frio 63 s → 26 s; quente 8 s → 0,3 s). Terminal: sugestões na busca
  (`COMANDOS`, ↑↓/Enter após navegar/Tab/Esc), "+N veículos" nas notícias, horário do painel em HH:MM (title com
  segundos).
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
  TERMINAL · TV · ACERVO · CONFIGURAÇÕES + selo do Telegram) em `index.html`, `acervo.html` e `config.html`. Sem `--central`
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
