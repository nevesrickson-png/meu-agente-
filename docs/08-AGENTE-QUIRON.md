# O agente do Quíron — o melhor de Hermes, Claude Code e OpenClaw, no Telegram

> **Decisão do Rickson (04/10/2026, item 5.2):** o runtime é o **bot próprio do Quíron**, construído em Python,
> inspirado no que há de melhor em cada referência — sem depender de nenhuma delas. O Hermes fica instalável
> como referência/plano B (`quiron-hermes-preparar`), mas não é o caminho principal.

## O que pegamos de cada um

| Ideia | De onde vem | Como fica no Quíron |
|---|---|---|
| **Arquivos do "cérebro" em Markdown**, editáveis à mão | OpenClaw (SOUL/USER/MEMORY/HEARTBEAT) | `agente/workspace/`: `SOUL.md` (persona, gerada), `USUARIO.md` (quem é o Rickson), `MEMORIA.md` (fatos duráveis), `ROTINAS.md` (o que vigiar), `diario/AAAA-MM-DD.md` |
| **Batimento (heartbeat) proativo** | OpenClaw | A cada 30 min (7h–22h) confere agenda, alertas de notícias da watchlist e `ROTINAS.md`; só chama o modelo se houver motivo; respeita **3 mensagens automáticas/dia** |
| **Memória que aprende** + busca em conversas antigas | Hermes (memory, session_search) | Ferramentas `lembrar` / `esquecer` / `buscar_conversas` (busca de texto completo em todas as conversas) |
| **Agendamentos em linguagem natural** | Hermes (cron) | "todo dia útil às 7h30 me manda o briefing", "amanhã às 10h me lembre de ligar para o CLI-012" → `agendar` |
| **Troca automática de modelo** | Hermes (fallback providers) | Já existe: Gemini grátis → Groq grátis |
| **Compactação do contexto** | Claude Code / Hermes | Conversa longa vira resumo automático; o essencial não se perde e a cota grátis rende mais |
| **Skills com carregamento sob demanda** | Claude Code / Hermes | Já existe: índice no prompt + `ler_skill` |
| **Agente que propõe melhorias em si mesmo, com aprovação** | Hermes (self-improving + write_approval) | `propor_skill` cria uma skill nova **só depois do seu ✅ no Telegram** |
| **Permissões por ferramenta** (livre / confirmar / bloqueado) | Claude Code | `config/agente.yaml`; ações sensíveis viram botão ✅/❌ no Telegram |
| **Hooks** (regras que rodam antes/depois) | Claude Code | Compliance automático: texto para cliente sai como **RASCUNHO**; análise de ação ganha o rodapé **"Uso interno — não constitui relatório de análise"** |
| **Comandos de barra escritos em Markdown** | Claude Code (slash commands) | `agente/comandos/*.md`: você cria um `/comando` novo escrevendo um arquivo |
| **Planejar antes de tarefas pesadas** | Claude Code (plan mode / todo) | Análises longas: o agente apresenta o plano e espera seu "ok" (motor de análise da Fase 7) |
| **Áudio** | Hermes / OpenClaw | Mensagem de voz → texto (Whisper grátis do Groq) — item 5.5 |

## O que fica de fora (de propósito)

- **Terminal, acesso a arquivos do sistema, navegador autônomo, controle do computador** (OpenClaw/Hermes/Claude Code têm):
  incompatível com um sistema que guarda dados de assessoria. O Quíron só age pelas ferramentas que nós escrevemos.
- **Loja aberta de skills/plugins de terceiros** (ClawHub e afins): histórico de skills maliciosas. Skills novas só nascem
  aqui e só com sua aprovação.
- **Vários canais** (WhatsApp, Discord…): só Telegram, com lista branca do seu ID.

## Ordem de construção (Fase 5)

1. **Workspace + contexto** (SOUL/USUARIO/MEMORIA/ROTINAS/diário) e comandos em Markdown.
2. **Memória**: lembrar/esquecer, busca em conversas antigas, compactação.
3. **Permissões e hooks de compliance**, com aprovação por botão no Telegram.
4. **Agendador + batimento proativo**, com o limite de 3 mensagens automáticas/dia.
5. **Skills que evoluem** (`propor_skill` com aprovação).
6. **Áudio** e servidor 24h (itens 5.3 a 5.8 do roteiro).
