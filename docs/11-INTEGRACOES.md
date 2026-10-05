# Integrações (Fase 18) — desenho proposto, ADIADO pelo Rickson em 05/10/2026

> Status: proposta em espera. O Rickson vai integrar o CRM depois. Retomar com:
> "Execute a FASE 18 do docs/00-ROTEIRO.md" e responder as 3 perguntas do fim deste arquivo.

## O que existe hoje
- **CRM próprio** (`nevesrickson-png/primeiro`, "CRM Assessor" v0.2.0): app Electron no PC, banco SQLite criptografado
  (`crm.db` ao lado do .exe), leads com etapa, perfil financeiro, aplicações, tarefas, interações, NPS e campanhas de
  e-mail; sincroniza só com a planilha Google (Apps Script). Não tem API aberta.
- **SDR de WhatsApp**: não encontrado nos repositórios. Falta saber onde ele vive.
- O Quíron **nunca** se conecta ao CRM da EQI.

## Regra de ouro
Nome, telefone, e-mail e textos livres (observações, resumos de interações) **nunca saem do CRM** para o Quíron
online. A ligação é pelo código **CLI-XXX**. Nomes reais só no cofre da versão offline.

## 18.1 CRM ↔ Quíron
1. CRM ganha a coluna `codigo_quiron` (nova migration); código criado ao virar "conta aberta" ou no botão
   "Vincular ao Quíron".
2. Botão **"Enviar ao Quíron"**: só dados sem identificação — etapa, origem, faixas de patrimônio/renda, suitability,
   objetivos, horizonte, produtos de interesse, idade (sem data de nascimento), UF (sem cidade), aplicações (produto,
   valor, vencimento), data/tipo da última interação, tarefas abertas, NPS, próxima revisão. Transporte: POST no
   Terminal pelo Tailscale com token; plano B: arquivo enviado ao bot.
3. Quíron (`quiron/servicos/crm/`, `dados/crm.db`): preenche a ficha (histórico; divergência pede confirmação),
   alimenta vencimentos, dossiê e briefing ("clientes sem contato há 60 dias"); comando `/crm` e ferramentas MCP.
4. Volta: botão **"Buscar do Quíron"** no CRM traz, pelo código, tarefas e próximo contato do `/pos`.

## 18.2 SDR (lead qualificado → dossiê)
- O SDR deposita o lead qualificado numa caixa de entrada (como a aba "Entradas" do Google Forms já faz no CRM);
  entra no CRM com origem "SDR" e o resumo da qualificação.
- Em "reunião agendada", o Quíron gera o **dossiê do prospect** (perfil, pontos a explorar, objeções prováveis,
  produtos que fazem sentido) como RASCUNHO, só com o código.

## 18.3 Versão offline
- O cofre offline recebe do CRM o mapa código → nome/contatos.
- O pacote offline leva o `crm.db` do Quíron (só códigos); o cofre continua fora do pacote.

## Perguntas pendentes para o Rickson
1. Onde está o SDR (repositório, ferramenta pronta ou ainda não existe)?
2. Pode alterar o app do CRM (código CLI-XXX + botões Enviar/Buscar → nova versão do .exe)?
3. Faixa de patrimônio e suitability podem ir ao Quíron (no servidor dele, só com o código)?
