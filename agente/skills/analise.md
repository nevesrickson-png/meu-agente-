# Skill: análises e contas (motor de análise)

**Quando usar:** pedido de estudo com números ("compare CDB e LCI", "vale mais Tesouro IPCA+ ou prefixado?",
"quanto rende…", "monte um relatório"), `/analise`, `/calc`, ou qualquer conta financeira.

## Contas rápidas → `quiron_analise__calcular`
- Juros compostos, equivalência de taxas, CDB × LCI, taxa real, % do CDI, financiamento (Price/SAC), VPL/TIR,
  aporte para meta, renda na aposentadoria, PU de prefixado, duration (`calculadoras_disponiveis` lista os campos).
- Mostre o resultado E a memória de cálculo. Nunca faça a conta de cabeça.

## Estudos com relatório → `quiron_analise__analisar`
1. Escolha o tipo (`tipos_de_analise`) e monte os parâmetros a partir do pedido; o que faltar, use o padrão e diga.
2. **Modo** (diga qual usou):
   - **entregar** (padrão): conclusão + porquês + principal risco;
   - **debater**: quando o Rickson pede para "pensar junto", comparar caminhos ou "prós e contras";
   - **contestar**: quando pede "advogado do diabo", "me convença do contrário", "onde isso pode dar errado".
3. Responda curto, sem linha "Modo:" (o modo aparece no relatório): "Pedido #N na fila. Te mando o resumo, o PDF e a
   planilha aqui assim que ficar pronto."
   Não antecipe números — eles vêm do relatório.
4. Para discutir um relatório pronto: `ler_relatorio` (cite as tabelas; não recalcule).

## Carteira de cliente → `carteira_diagnostico`
1. **Leitura:** print e planilha chegam pelo Telegram já lidos (OCR local) e guardados com um id `CART-…`.
   Carteira em texto: chame `ler_carteira(texto, perfil, cliente)`. Cliente **só** como CLI-XXX.
2. **Confira com o Rickson** antes de analisar quando houver aviso (OCR, classe duvidosa, posição sem valor) ou
   perfil não informado: mostre o resumo e pergunte o que corrigir (corrija chamando `ler_carteira` de novo).
3. `analisar("carteira_diagnostico", {"carteira_id": "CART-…", "perfil": "...", "aporte": 0})` — nunca retranscreva
   as posições; use o id. O relatório traz enquadramento no perfil, risco (vol, VaR, drawdown, beta, duration),
   stress (Selic ±3 p.p., bolsa −20%, dólar +20%, inflação, crises), otimização, rebalanceamento com IR e backtest.
4. Ao discutir: o stress é choque instantâneo + carregamento do pós-fixado em 12 meses; a otimização depende das
   premissas de retorno (`config/premissas_carteira.yaml`) — trate como referência, não como verdade.

## Compliance
Uso interno e de estudo. Não é recomendação a cliente; texto para cliente só como RASCUNHO e sem promessa de rentabilidade.
