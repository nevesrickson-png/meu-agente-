---
skill: fundos
padrao: como comparo fundos imobiliários?
descricao: FIIs com o informe mensal da CVM (ex.: /fii HGLG11 KNRI11 XPML11) — um só = consulta rápida
---
FIIs: {args}. Se for um só, use quiron_mercado__fii_dados; se forem vários, peça
quiron_analise__analisar("fii_comparativo", {"fiis": [...]}) e me diga o número do pedido.
