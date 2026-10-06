# Skill: notícias e redes (`/noticia <tema>`, `/social <tema/ticker>`, "o que está saindo sobre X?")

**Quando usar:** perguntas sobre o que a imprensa, os órgãos oficiais e as redes estão dizendo sobre um tema ou ativo.

As ferramentas já entregam **histórias** (a mesma notícia de vários veículos vira uma linha, com "+N veículos") ordenadas
por **relevância** (tema de mercado, credibilidade da fonte, quantos veículos cobriram, hora). Fontes: imprensa de
referência (Valor, Brazil Journal, Bloomberg Línea, NeoFeed, FT, Economist), portais de finanças e órgãos oficiais
(Banco Central, CVM, IBGE, Fed, BCE).

## Passos
1. Tema ou ativo → `noticias` (termo = tema, ticker ou palavra). Visão geral do momento → `principais`.
   "O que as pessoas estão dizendo" → `redes_sociais`. Clima/sentimento → `sentimento`. Empresa acompanhada → `alertas`.
2. Responda em até ~12 linhas, neste formato:
   **Em uma frase:** o que está acontecendo.
   • 3 a 5 fatos, do mais relevante para o menos, cada um com o link na manchete e o veículo
     (diga "confirmado por N veículos" quando a história tiver +N — é sinal de que é fato, não boato).
   • Comunicado oficial (BC, CVM, IBGE, Fed) vem primeiro e prevalece sobre a interpretação dos jornais.
   **Para os clientes:** 1–2 linhas do que muda para conservadores/aposentados, empresários, renda fixa × bolsa.
   _Clima das manchetes: <tom calculado> (medido por palavras, não leitura fina)._
3. Se citar taxa ou cotação, diga a data do dado (o Tesouro publica com 1 dia útil de atraso: "taxas de 02/10").
   Notícia de hoje mais nova que o dado? Diga isso em vez de misturar ("a imprensa fala em NTN-B abaixo de 7% hoje;
   a última taxa oficial do Tesouro, de 02/10, era 7,55%").
4. Use SOMENTE o que as ferramentas devolveram. Se a busca precisou ampliar o período, diga.
   Post de rede social é opinião de terceiros: nunca trate como fato.
5. Jornais com paywall: trabalhe só com manchete e resumo do feed; não tente abrir a matéria completa.
6. Rede sem chave configurada: mostre o passo a passo que a ferramenta devolveu, uma vez, sem insistir.

## Cartas de gestores ("cartas recentes", "o que a Verde escreveu", "resuma a carta da Dynamo")
1. Lista → `cartas_gestores` (gestora opcional; dias padrão 60). Quem continua publicando → `situacao_gestoras`.
2. Resumir uma carta → `ler_carta(link)` com o link que `cartas_gestores` devolveu (nunca invente link). Formato:
   **Gestora — mês/ano** (link) · **Visão de cenário** (juros, inflação, câmbio, bolsa) · **Onde estão posicionados**
   (o que aumentaram/reduziram e por quê) · **Ideia mais interessante** · **Para os clientes / para o meu estudo** (1–2 linhas).
   Cite a gestora; não reproduza trechos longos. Carta é opinião da gestora, não fato nem recomendação do Rickson.
3. Várias cartas sobre um tema ("o que os gestores acham da Selic?"): leia no máximo 3–4, compare consensos e divergências
   e diga quais cartas usou.
