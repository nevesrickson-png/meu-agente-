# Skill: planejamento financeiro (padrão CFP)

**Quando usar:** "monte o planejamento do CLI-XXX", aposentadoria, sucessão/herança/ITCMD, imposto de renda/PGBL,
seguros/proteção, "vale abrir PJ?", `/cliente`, `/planejamento`, `/aposentadoria`, `/sucessao`, `/tributario`,
`/protecao`, `/empresario`.

## 1. Ficha do cliente → `quiron_assessoria__*`
- Cliente **só** como CLI-XXX. Se o Rickson digitar nome, CPF, endereço ou telefone, **não guarde** e lembre a regra.
- `ver_ficha` primeiro. Sem ficha: `campos_da_ficha` e monte conversando, **poucas perguntas por vez**, na ordem:
  família (idade, UF, estado civil, regime de bens, filhos) → renda e despesas → patrimônio e dívidas → seguros e
  INSS → objetivos e aposentadoria → perfil → empresa (se empresário/liberal).
- Grave aos poucos com `salvar_ficha` (mescla). Mostre as pendências que voltarem; dá para rodar o plano com
  pendências, mas diga o que fica impreciso (ex.: sem INSS a aposentadoria é conservadora).
- Valores "de hoje" (o plano corrige pela inflação). Despesas **sem** as parcelas de dívidas (elas vão em `dividas`).

## 2. Plano → `quiron_analise__analisar`
- Completo: `analisar("planejamento_completo", {"cliente": "CLI-XXX"})`. Módulos: `aposentadoria`, `sucessao`,
  `tributario`, `protecao`, `empresario` (mesmo parâmetro). Modo entregar/debater/contestar como nas outras análises.
- Responda curto com o número do pedido; os números vêm do relatório (não antecipe).

## 3. Discutindo o plano (como planejador CFP)
- Ordem de prioridade: orçamento no azul → dívidas caras → reserva → proteção (vida/invalidez/saúde) → objetivos
  essenciais → aposentadoria → otimização tributária e sucessória.
- Aposentadoria: diferencie o **cenário médio** do **Monte Carlo** (85% de chance). Quando os aportes passam da sobra,
  mostre as alavancas com números do relatório: aportar mais, aposentar depois, reduzir a renda, rever objetivos.
- Sucessão: meação não é herança; previdência e seguro ficam fora do inventário; ITCMD calculado com a alíquota máxima
  do estado (conferir a tabela vigente). Testamento, doação com usufruto e holding são decisões jurídicas: indique
  advogado.
- Tributário e PF × PJ são estimativas para levar ao contador.
- Material para o cliente sai como **RASCUNHO** e sem promessa de rentabilidade.

## 4. LGPD
`/esquecer CLI-XXX` → `quiron_assessoria__esquecer_cliente` (pede confirmação): apaga ficha, carteiras, relatórios,
conversas e memória que citam o código.
