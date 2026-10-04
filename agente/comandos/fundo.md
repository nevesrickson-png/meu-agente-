---
skill: fundos
padrao: como peço a análise de um fundo?
descricao: Análise de um fundo com dados da CVM (ex.: /fundo Verde 30 ou /fundo 22.215.116/0001-80)
---
Análise do fundo: {args}. Ache o CNPJ com quiron_mercado__buscar_fundo (se houver várias opções, me mostre e pergunte)
e peça quiron_analise__analisar("fundo_analise", {"cnpj": ...}); me diga o número do pedido.
