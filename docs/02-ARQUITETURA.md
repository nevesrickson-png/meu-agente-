# Arquitetura

## Visão geral
```
                        ┌──────── RUNTIME DO AGENTE (decidido na Fase 5) ────────┐
   VOCÊ ── Telegram ──► │  Hermes  |  baseado em Claude  |  bot próprio Python   │
                        └───────────────────────┬────────────────────────────────┘
   VOCÊ ── Claude Code ─────────────────────────┤  (interface de teste nas Fases 0–4)
                                                │ MCP
     ┌──────────┬──────────┬──────────┬─────────┼──────────┬────────────┬───────────┐
 biblioteca  academia   mercado   notícias   análise   assessoria   carreira
     └──────────┴──────────┴──────────┴─────────┼──────────┴────────────┴───────────┘
                                                │ mesmos serviços
   VOCÊ ── navegador ──► QUÍRON TERMINAL (painéis, barra de comando, chat)
```

## Ferramentas primeiro, agente depois
- Toda a inteligência fica em servidores MCP em Python, independentes de runtime.
- Desde a Fase 1 você já usa as ferramentas pelo Claude Code (registradas no `.mcp.json`).
- Quando o runtime for escolhido (Fase 5), ele só se conecta aos MCP prontos. Nada é refeito.
- Instruções de comportamento ficam em `agente/skills/` (Markdown neutro), reaproveitáveis por qualquer runtime.

## Servidores MCP
| MCP | Ferramentas principais |
|---|---|
| `quiron-biblioteca` | buscar trechos, ficha de livro, mapa de autor, cobertura dos 22 blocos |
| `quiron-academia` | aula, questões, simulado, diagnóstico, plano de estudo, flashcards |
| `quiron-mercado` | cotações, curva de juros, Tesouro, macro/Focus, agenda econômica, alertas |
| `quiron-noticias` | notícias RSS, Bluesky, Reddit, YouTube; busca por tema e resumo de sentimento |
| `quiron-analise` | fila, relatórios PDF/planilha, carteira, risco, otimização, valuation, fundos, planejamento, calculadoras |
| `quiron-assessoria` | dossiê de reunião, pós-reunião, treino com cliente simulado, mensagens (RASCUNHO), vencimentos |
| `quiron-carreira` | plano de carreira, diário de decisões, radar regulatório |

## Onde roda cada coisa
| Fases | Onde | Como |
|---|---|---|
| 0 a 4 | Seu PC (8 GB) | `uv`, sem Docker; biblioteca só em piloto (3 livros); Terminal local |
| 5 em diante | Host Linux 24h | Docker Compose, Tailscale, backup noturno; biblioteca completa |
| 16 | Seu PC, offline | modelo local leve (3–4B) + MCP leves + Terminal local |

## Cérebro trocável — faixas de custo
| Faixa | Cérebro | Custo aproximado |
|---|---|---|
| Grátis (agora) | Gemini Flash grátis + Groq grátis de reserva | R$ 0 |
| Baixo custo | Gemini pago, DeepSeek ou Claude Haiku | ~US$ 5–15/mês |
| Custo ok | Claude Sonnet | ~US$ 20–50/mês |
Camadas pagas não usam seus dados para treino. Confirme preços antes de migrar.

## Motor de análise pesada
Pedido → fila → coleta de dados oficiais → cálculos em Python → cérebro interpreta e redige →
relatório Markdown com gráficos → PDF (+ planilha) → entrega no canal e na aba Relatórios do Terminal.

## Biblioteca (RAG híbrido)
Ingestão (PDF, OCR, EPUB) → fichas por livro → trechos com metadados → embeddings multilíngues locais → Chroma.

## Segurança
Telegram com lista branca do seu ID. Terminal no host só pela rede Tailscale + senha. Zero portas públicas além do SSH.

## Portabilidade
`deploy/migrar.sh`: backup → novo host → `docker compose up` → restaurar. Meta: menos de 1 hora. Testado com simulado de desastre.
