# Skill: fundos, gestoras, previdência e alternativos

**Quando usar:** "analise o fundo X", "compare estes fundos", "como está a gestora Y", portabilidade de previdência,
FIIs, `/fundo`, `/comparar_fundos`, `/gestor`, `/previdencia`, `/fii`, `/alternativos`.

## Dados (sempre oficiais)
- Tudo vem da **CVM Dados Abertos**: cadastro (Resolução CVM 175), informe diário (cotas), extrato (taxas/prazos) e
  informe mensal de FII. Rentabilidade = razão de cotas (líquida de taxas, antes do IR). Nunca use número de memória.
- Ache o CNPJ com `quiron_mercado__buscar_fundo("nome")` — se houver vários (feeder, espelho, master, previdência),
  mostre as opções e pergunte qual o cliente acessa. Master e fundos com 1 cotista não são o produto do cliente.

## Análises → `quiron_analise__analisar`
- Um fundo: `fundo_analise {"cnpj": ...}` · vários: `fundos_comparativo {"cnpjs": [...], "anos": 3}` (2 a 6).
- Gestora: `gestora {"gestora": "nome ou CNPJ"}` (use `buscar_gestora` antes se o nome for ambíguo).
- Previdência: `previdencia_portabilidade {"cnpj_atual", "cnpj_destino", "saldo", "aporte_mensal", "anos",
  "renda_mensal_aposentadoria"}`.
- FIIs: `fii_comparativo {"fiis": ["HGLG11", ...]}` (traz também imóveis, estados, vacância, inquilinos e CRIs do
  informe trimestral). Consulta rápida: `quiron_mercado__fii_dados` (números do mês) + `quiron_mercado__fii_imoveis`
  (o que o fundo tem e onde). Variação de preço na semana/mês/ano: `quiron_mercado__desempenho`.
- A 1ª análise baixa ~3 anos de cotas da CVM (alguns minutos, uma vez); avise o Rickson.

## Como discutir (padrão CFA/CAIA)
- Compare com o benchmark certo (CDI para RF/multimercado; Ibovespa para ações) e com os **pares** (percentil).
- Retorno sozinho não basta: volatilidade, pior queda, Sharpe, consistência (% de meses acima do CDI), fluxo
  (captação/resgates), taxas e **liquidez** (D+ de cotização/pagamento) — e se o cliente aguenta esse resgate.
- Previdência: portabilidade não paga IR e mantém regime/datas; compare taxa e gestão; regressiva × progressiva
  depende do prazo e da renda na saída.
- Alternativos: FII (P/VP, DY sobre o preço com proventos pagos, segmento, liquidez); FIDC/FIP/COE só com explicação
  de riscos (crédito, iliquidez, complexidade) e público-alvo (qualificado/profissional).
- Rentabilidade passada não garante futuro. Nada é recomendação ao cliente; texto para cliente sai como RASCUNHO.
