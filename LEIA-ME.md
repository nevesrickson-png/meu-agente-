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


## Próximas fases
Siga o `docs/00-ROTEIRO.md`: abra o `claude` na pasta e cole o prompt da próxima fase.
