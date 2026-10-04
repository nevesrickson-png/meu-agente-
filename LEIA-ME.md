# Kit de arranque — Quíron, o parceiro de análise do assessor
> Sistema pessoal e de propriedade de Rickson Messias. Independente da EQI.
*(Nome definido: Quíron.)*

## O que é
Um agente de nível especialista (repertório CFP, CFA, CAIA, FRM, CGA/CGE, CNPI) com duas faces:
o **agente no Telegram** e o **Quíron Terminal**, uma tela estilo terminal profissional de mercado.

## A estratégia: ferramentas primeiro, agente depois
Você começa **hoje, no seu PC, de graça**. Cada capacidade do Quíron é construída como uma ferramenta (MCP)
que você já usa conversando com o Claude Code. O agente 24h do Telegram (Hermes, Claude ou bot próprio)
e o servidor são escolhidos só na Fase 5, depois de você testar tudo. Nada é refeito.

## Arquivos
| Arquivo | Para que serve |
|---|---|
| `docs/00-ROTEIRO.md` | **Comece aqui:** 19 fases, checklist inicial, itens numerados, testes de aceite e prompts |
| `CLAUDE.md` | Manual que o Claude Code lê sozinho |
| `docs/01-FUNCIONALIDADES.md` | Tudo o que o Quíron faz |
| `docs/02-ARQUITETURA.md` | Ferramentas MCP, Terminal, onde roda cada coisa |
| `docs/03-HOSPEDAGEM.md` | Opções de servidor 24h (decisão na Fase 5) |
| `docs/05-MATERIAIS-GRATUITOS.md` | Materiais gratuitos para a Academia |
| `docs/06-TERMINAL.md` | Especificação do Quíron Terminal |
| `docs/07-DECISAO-RUNTIME.md` | Hermes × Claude × bot próprio (decisão na Fase 5) |
| `config/*.yaml` | Persona, trilha de certificações, watchlist, fontes de notícias |
| `.env.example` | Modelo das chaves (todas gratuitas) |

## As fases
**No seu PC:** 0. Fundação · 1. Biblioteca e Mentor · 2. Dados de mercado · 3. Notícias e redes · 4. Terminal v1
**No servidor 24h:** 5. Agente no Telegram · 6. Academia · 7. Motor de análise · 8. Carteiras e risco · 9. Planejamento CFP ·
10. Fundos · 11. Valuation · 12. Terminal v2 · 13. Assessoria · 14. Organização · 15. Carreira e radar · 17. Conteúdo · 18. Integrações
**De volta ao PC:** 16. Versão offline

## Custo
R$ 0. Nenhuma API paga. (X/Twitter fora do projeto.)

## Rodar no seu PC (Windows)
Uma vez só:
1. Instale o `uv` (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Baixe o projeto: `git clone https://github.com/nevesrickson-png/meu-agente-.git C:\projetos\quiron`
3. Na pasta: `copy .env.example .env` e abra o `.env` no Bloco de Notas. Preencha `GEMINI_API_KEY` (e `GROQ_API_KEY`, se tiver).
4. `uv sync` (instala o Python 3.12 e as bibliotecas dentro da pasta; não mexe no resto do PC).

Testes:
- `uv run pytest` → deve terminar com "passed" e nenhum "failed".
- `uv run quiron-testar-cerebro` → deve mostrar ✅ no Gemini (testa sua chave de verdade).
- `claude` na pasta → aprove os servidores `quiron-sistema` e `quiron-biblioteca` → peça "use a ferramenta ping do Quíron".

## Biblioteca (Fase 1)
1. Para PDFs escaneados, instale o OCR (uma vez): Tesseract com português (https://github.com/UB-Mannheim/tesseract/wiki,
   marque "Portuguese" na instalação) e Ghostscript (https://ghostscript.com). PDFs com texto e EPUBs não precisam.
2. Coloque os livros em `biblioteca\entrada\`. Dica: nomeie como `Autor - Título.pdf`, ou crie `Título.yaml` ao lado
   com `titulo:` e `autor:` para corrigir os dados.
3. `uv run quiron-ingerir` → processa e mostra o resultado (o 1º uso baixa o modelo de ~220 MB).
4. Preencha `config\guia_22_blocos.yaml` e peça no Claude Code: "use a ferramenta reclassificar".
5. Teste: no `claude`, "me explica duration usando a biblioteca".


## Dados de mercado (Fase 2)
1. Opcional: token gratuito da brapi (brapi.dev) em `BRAPI_TOKEN` no `.env` (sem ele, só alguns tickers funcionam).
2. `uv run pytest -m online` → confere todas as fontes reais (precisa de internet).
3. `uv run quiron-briefing` → mostra os dados do briefing no terminal.
4. No `claude`: "faça meu briefing" (aprove o servidor `quiron-mercado`).
5. Confira as datas do Copom em `config\agenda_fixa.yaml` e acrescente resultados de empresas que acompanha.

## Notícias e redes (Fase 3)
- Notícias funcionam sem chave: `uv run quiron-noticias` (principais), `uv run quiron-noticias copom`, `uv run quiron-noticias --fontes`.
- No `claude`: "o que está saindo sobre o Copom?" (aprove o servidor `quiron-noticias`).
- Chaves gratuitas das redes (coloque no `.env`):
  1. **Bluesky:** app do Bluesky → Configurações → Privacidade e segurança → Senhas de app → Adicionar.
     `BLUESKY_HANDLE=seu.usuario.bsky.social` e `BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx`.
  2. **Reddit:** https://www.reddit.com/prefs/apps → "create another app" → tipo **script**, redirect `http://localhost:8080`.
     `REDDIT_CLIENT_ID` = código abaixo do nome do app; `REDDIT_CLIENT_SECRET` = "secret".
  3. **YouTube:** https://console.cloud.google.com → novo projeto → APIs e serviços → ative "YouTube Data API v3" →
     Credenciais → Criar credencial → Chave de API. `YOUTUBE_API_KEY=...` (cota grátis ≈ 100 buscas/dia).
- Ajuste temas, palavras-alerta e empresas em `config\temas_noticias.yaml`; subreddits em `config\redes.yaml`.

## Quíron Terminal (Fase 4)
- **Dois cliques em `Quiron Terminal.bat`** (na pasta do projeto): abre o Terminal no navegador. Feche a janela preta para desligar.
  Pelo terminal: `uv run quiron-terminal`.
- Barra de comando (atalho `/` ou `Ctrl+K`): `PETR4` (visão do ativo), `PETR4 GP` (gráfico), `CURV`, `TOP`, `NEWS COPOM`,
  `SOC COPOM`, `ECO`, `MACRO`, `JUROS`, `WEI`, `FX`, `CMDTY`, `CALC`, `STATUS`, `HELP`.
- Layouts prontos: Manhã, Análise, Estudo (`Alt+1/2/3`). Arraste o cabeçalho para mover, o canto para redimensionar;
  "Salvar" guarda o layout com um nome.
- Só abre no seu próprio PC (endereço local). Na Fase 5, no servidor, ganha senha (`TERMINAL_SENHA`) e acesso pelo Tailscale.

![Quíron Terminal](docs/img/terminal-v1.png)

## Agente no Telegram (Fase 5)
> **Um clique:** `Abrir Quiron.bat` instala na 1ª vez (Git, uv, programa), baixa a versão mais nova a cada clique
> (todas as versões ficam guardadas na pasta) e abre o bot. Cria o atalho **Quiron** na Área de Trabalho.
> Seus dados (`.env`, `dados\`, `biblioteca\`) nunca são apagados nem enviados.
> **Configurações:** chaves e seu ID do Telegram numa tela no navegador (atalho **Quiron - Configuracoes**, ou
> `uv run quiron-configurar`), com botão **Testar** em cada chave e **Descobrir meu ID**. Abre sozinha se faltar algo.

1. **Crie o bot:** no Telegram, fale com **@BotFather** → `/newbot` → escolha nome e usuário → copie o token.
2. **Descubra seu ID:** fale com **@userinfobot** → ele responde com seu número.
3. No `.env`: `TELEGRAM_BOT_TOKEN=...` e `TELEGRAM_ALLOWED_USER_IDS=seu-numero` (só você fala com o Quíron).
4. Comparativo dos runtimes (precisa de `GEMINI_API_KEY`): `uv run quiron-comparativo` → relatório em `dados\comparativo\`.
5. Testar o agente: `uv run quiron-agente -q "faça meu briefing"` (sem Telegram). **Ligar no Telegram pelo PC:** dois cliques
   em `Quiron Telegram.bat` (religa sozinho se cair); para ligar junto com o Windows, `Quiron Inicio Automatico.bat`.
   O bot só roda em um lugar por vez — ao passar para o mini PC, desligue o do PC.
6. O "cérebro" editável fica em `dados\workspace\`: `USUARIO.md` (quem é você), `MEMORIA.md` (o que ele aprendeu),
   `ROTINAS.md` (o que vigiar sozinho) e `diario\`. Comandos novos: crie `agente\comandos\<nome>.md`.
7. No Telegram: `/ajuda`, `/briefing`, `/noticia <tema>`, `/estudar <tema>`, `/agenda`, `/memoria`, `/novo`; peça
   "todo dia útil às 7h30 me manda o briefing" ou "me lembre amanhã às 10h de…". Ações sensíveis chegam com botões ✅/❌.
8. **Áudio:** mande uma mensagem de voz — ele transcreve (Whisper grátis do Groq, usa a mesma `GROQ_API_KEY`) e responde.
9. O briefing diário das 7h30 já vem criado (veja `/agenda`; cancele ou mude pedindo no chat).

## Academia — CFP (Fase 6)
No Telegram: **/academia** (painel) · **/simulado** (mini, 16 questões, 2 por módulo; também `/simulado 40` ou
`/simulado completo`) · **/questoes** `[módulo, código ou tema]` (botões A–D) · **/flashcards** · **/diagnostico** ·
**/plano** `[horas]` · **/aula** `<tema>` · **/caso** `[tema]`. Diga “minha prova do CFP é em dd/mm/aaaa” para o plano contar os dias.
- O edital oficial do CFP está mapeado (8 módulos, pesos e 922 tópicos) em `config/editais/CFP.yaml`.
- Questões geradas por IA (Groq) e conferidas por um 2º modelo (Gemini); contas conferidas em Python. Achou erro? Toque **⚠**.
- O banco cresce sozinho de madrugada (01h–06h, `config/academia/geracao.yaml`). Pelo terminal: `uv run quiron-academia status`
  ou `uv run quiron-academia gerar --modulo 3 --n 8`.
- Suas apostilas: coloque em `academia\material\CFP\` e rode `uv run quiron-ingerir --academia` (aulas e questões passam a citar o seu material).
- Materiais gratuitos conferidos: `config/materiais_gratuitos.yaml` (nada é baixado sem você aprovar).

## Servidor 24h (mini PC em casa; VPS no futuro) — detalhes em `docs/03-HOSPEDAGEM.md`
Tudo roda em Docker; o Terminal só é acessível pelo Tailscale (nenhuma porta aberta além da 22).
1. No servidor novo, como root: `bash deploy/preparar_host.sh "sua-chave-ssh-publica"` (segurança, Docker, Tailscale).
2. `sudo tailscale up` (entre com a sua conta Tailscale).
3. Como usuário `quiron`: `git clone <repositório> ~/quiron && cd ~/quiron && bash deploy/instalar.sh`
   (na 1ª vez ele cria o `.env`: preencha as chaves e uma `TERMINAL_SENHA`, depois rode de novo).
4. Backup automático às 3h (`deploy/backup.sh`; Google Drive opcional com `rclone`). Restaurar: `deploy/restaurar.sh`.
   Mudar de servidor: `bash deploy/migrar.sh quiron@novo-servidor`.

## Próximas fases
Siga o `docs/00-ROTEIRO.md`: abra o `claude` na pasta e cole o prompt da próxima fase.
