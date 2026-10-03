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
2. Rodar 10 pedidos reais (briefing, pergunta da biblioteca, análise curta, tarefa, pedido com dado de cliente anonimizado).
3. Comparar qualidade, velocidade, estabilidade, facilidade de ajuste e se as regras de compliance foram respeitadas.
4. Escolher e registrar em `.env` (`RUNTIME_AGENTE`).
