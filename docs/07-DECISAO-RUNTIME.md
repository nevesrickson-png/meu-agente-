# Decisão do runtime do agente (Fase 5)

"Runtime" é o programa que conversa com você no Telegram, decide quais ferramentas usar e roda as rotinas agendadas.
Como todas as ferramentas do Quíron são servidores MCP, **qualquer opção abaixo funciona sem refazer nada**.

## As quatro opções
| Critério | OpenClaw | Hermes Agent | Claude Code / Claude | Bot próprio (Python) |
|---|---|---|---|---|
| Custo | Grátis + modelo grátis | Grátis + modelo grátis | Assinatura ou API (pago) | Grátis + modelo grátis |
| Raciocínio | Depende do modelo | Depende do modelo | O mais alto | Depende do modelo |
| Telegram, memória, agendamentos | Prontos | Prontos | Precisa de ponte | Construídos por nós |
| Ferramentas MCP | Sim | Nativo | Nativo | Via biblioteca MCP |
| Segurança / compliance | **Risco alto**: histórico de skills maliciosas e instâncias expostas; exige blindagem forte | Bom, revisar skills que ele próprio reescreve | Bom | **O mais controlável** |
| Previsibilidade | Média | Média (evolui sozinho) | Alta | Total |
| Esforço | Baixo para subir, alto para blindar | Baixo | Médio | Médio |

## Decisão recomendada
1. **OpenClaw: descartado** pelo histórico de segurança, incompatível com dados de clientes de um assessor.
2. **Hermes: primeira aposta** (máximo pronto, custo zero).
3. **Bot próprio: plano B** (controle total; sempre possível).
4. **Claude:** construtor do projeto (Claude Code) desde o início e "cérebro premium" futuro de qualquer runtime.

## Como decidir na Fase 5
1. Montar Hermes e bot próprio com as mesmas ferramentas MCP (1 tarde cada).
2. Rodar 10 pedidos reais (briefing, pergunta da biblioteca, análise curta, tarefa, pedido sobre cliente CLI-XXX).
3. Comparar qualidade, velocidade, estabilidade, facilidade de ajuste e se as regras de compliance foram respeitadas.
4. Escolher e registrar em `.env` (`RUNTIME_AGENTE`).

## O que já foi verificado (04/10/2026, antes do teste com o modelo)

| | Hermes Agent | Bot próprio (Quíron) |
|---|---|---|
| Instalação | Instalador oficial; **~2,4 GB** (código + dependências + cache) | Usa o ambiente do projeto (+ biblioteca do Telegram, poucos MB) |
| Ferramentas do Quíron (MCP) | ✅ conectou aos 4 servidores; viu as 11 ferramentas de mercado | ✅ conecta aos mesmos servidores pelo `.mcp.json` |
| Skills do Quíron | ✅ carregadas (geradas de `agente/skills/`) | ✅ índice no prompt + leitura sob demanda |
| Persona | `SOUL.md` gerado de `agente/persona.md` | `agente/persona.md` no prompt |
| Gemini grátis | Suporte nativo, **mas a doc oficial avisa que a camada grátis é pequena para sessões de agente** | Via LiteLLM, com troca automática para Groq grátis |
| Segurança | Terminal, arquivos, navegador, computador e código **desligados** na nossa config; auto-edição de skills só com aprovação | Só existe o que nós escrevemos: ferramentas do Quíron + leitura de skills |
| Telegram | Pronto (lista branca `TELEGRAM_ALLOWED_USERS`) | Pronto (`quiron-telegram`, lista branca, silêncio para estranhos) |
| Memória, agendamentos, áudio | Prontos | Memória das últimas 6 trocas; agendamentos e áudio a construir (5.5/5.7) |

O teste com os 10 pedidos (`uv run quiron-comparativo`) mede tempo, tokens (cota grátis), ferramentas usadas e
conferências de compliance (RASCUNHO, uso interno, não fingir que agendou, citar fontes, manter CLI-XXX) e gera um
relatório com as respostas lado a lado para você dar nota. Ele precisa da chave do Gemini.
