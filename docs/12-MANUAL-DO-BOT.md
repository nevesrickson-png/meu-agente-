# Manual do Quíron — o que ele faz e como pedir

Atualizado em 05/10/2026. O Quíron é o seu parceiro de análise, professor e secretário. Ele atende por dois lugares:
**Telegram** (no celular, por texto, áudio, foto ou planilha) e **Terminal** (no navegador do PC, com painéis e um
chat igual ao do Telegram). Tudo o que está aqui funciona nos dois, salvo quando indicado.

---

## 1. Como falar com ele

| Jeito | Como funciona |
|---|---|
| **Fala normal** | Escreva como falaria com um assistente. Frases do dia a dia viram a função na hora, sem IA (veja a tabela abaixo). O resto vai para a IA, que escolhe a ferramenta certa. |
| **Áudio** | Mande um áudio. Ele mostra o que entendeu (🎙️ “…”) e responde como se fosse texto. |
| **Foto ou planilha de carteira** | Print da carteira (lido no seu PC, sem mandar a imagem para a nuvem) ou planilha .xlsx/.csv: ele lê, guarda e faz o diagnóstico. |
| **Botões** | Respostas trazem botões: sugestões de próximo passo (» …), ✅ Feito / +1h / Amanhã nos lembretes, respostas de questões e ✅ Aprovar / ❌ Negar nas ações sensíveis. |
| **Comandos com /** | Atalhos para quem já sabe o que quer. Toque em “/” ao lado do campo de mensagem para ver o menu. `/ajuda` lista todos. |

**Frases que ele entende na hora (sem gastar IA)**

| Você escreve | Ele faz |
|---|---|
| “me lembra amanhã às 10h de ligar pro CLI-012” | cria a tarefa com lembrete |
| “na verdade passa para as 11h” · “pronto, fiz” (logo depois) | remarca ou conclui essa tarefa |
| “terminei a 3” · “adia a 3 para sexta” | conclui ou adia a tarefa nº 3 |
| “o que tenho hoje?” · “minhas tarefas” | seu dia (tarefas, agenda, vencimentos) ou a lista de tarefas |
| “anota: estudar duration” | guarda uma nota (com data, vira tarefa) |
| “me dá uma questão de renda fixa” · “quero fazer um simulado” | Academia |
| “quando posso parar de trabalhar com 1 milhão e 8 mil por mês?” | simulador de patrimônio com gráfico |
| “o que você sabe sobre mim?” · “o que fizemos hoje?” · “lembre que…” | memória |
| “tem norma nova?” · “me dá ideias de post” | radar regulatório · pautas de conteúdo |

Enquanto pensa, ele mostra **“⏳ Consultando dados de mercado…”**. A conversa tem continuidade: “e o IPCA?” depois de
perguntar da Selic é entendido. `/novo` começa outro assunto (o anterior fica guardado na memória).

---

## 2. O que ele faz sozinho (sem você pedir)

| Quando | O quê |
|---|---|
| Todo dia, 7h30 | Briefing de mercado (veja abaixo) |
| Segunda, 8h20 | Radar regulatório: normas novas da CVM, Receita, Banco Central e projetos na Câmara |
| Domingo, 18h | Revisão da semana (tarefas, metas, teses a revisar) |
| Na hora marcada | Lembretes das tarefas, com botões Feito / +1h / Amanhã |
| A cada 5 min | Confere seus alertas de preço, variação e notícia e avisa uma vez por disparo |
| Quando fica pronta | Entrega a análise pedida (resumo + PDF + planilha) |
| De 2 em 2 h (7h–22h) | Confere suas rotinas e só fala se valer a pena |
| Toda noite, 3h | Organiza a memória e faz cópia de segurança |

Ele manda no máximo 3 mensagens automáticas por dia além dos lembretes que você pediu. `/agenda` mostra e cancela rotinas.

---

## 3. Funções por área

### ☀️ Briefing (`/briefing`, “faz meu briefing” ou sozinho às 7h30)
Montado direto dos dados, sempre no mesmo formato, para ler no celular:
1. **O que está mexendo com o mercado** — as 5 histórias mais relevantes das últimas 18 h, com link e quantos veículos
   cobriram (sem deixar um assunto só ocupar tudo).
2. **Juros** — Selic e CDI; Tesouro prefixado e IPCA+ (curto, médio e longo) com a variação do dia em bps (▲/▼).
3. **Inflação e expectativas** — IPCA 12 meses e Focus (IPCA do ano e do próximo, Selic) com a mudança na semana.
4. **Mercados** — dólar, Ibovespa, S&P 500 e Brent com a variação.
5. **Agenda** — hoje e os próximos dias (Copom, IPCA, PIB, varejo, serviços, desemprego).
6. **Para os clientes** — 2 ou 3 linhas da IA do que isso muda para aposentados, empresários e liberais. Se ela citar
   um número que não está no briefing, a linha é descartada. Sem IA (cota esgotada), o briefing sai igual, sem essa parte.
7. Fontes e horários numa linha no fim; fonte fora do ar aparece como aviso, nunca com número inventado.

### 📊 Mercado e notícias
| Pedido | Comando | Exemplo |
|---|---|---|
| Briefing agora | `/briefing` | “faz meu briefing” |
| Taxas, cotações, curva, Focus, macro | — (fale normal) | “qual a Selic e o dólar?”, “como está a curva de juros?” |
| Notícias de um tema ou ativo | `/noticia` | `/noticia copom` |
| Clima nas redes (Bluesky, Reddit, YouTube) | — | “qual o sentimento sobre PETR4?” |
| Alertas | `/alerta` | `/alerta PETR4 abaixo de 30` · `/alerta "fato relevante" Vale` |

Dados de fontes oficiais (Banco Central, Tesouro, ANBIMA, CVM, IBGE, B3/Yahoo), sempre com fonte e horário. Fonte fora
do ar → último valor marcado DESATUALIZADO.

**Notícias — 24 fontes, organizadas por relevância.** Imprensa de referência (Valor, Brazil Journal, Bloomberg Línea,
NeoFeed, Financial Times, The Economist), portais de finanças (InfoMoney, Folha Mercado, Estadão E-Investidor, Exame,
Money Times, Seu Dinheiro, g1, Agência Brasil, CNBC, MarketWatch, BBC) e órgãos oficiais (Banco Central, CVM, IBGE,
Federal Reserve, BCE). A mesma notícia em vários veículos vira **uma história** (“+3 veículos” = confirmada). A ordem
leva em conta o tema (juros, inflação, fiscal e Copom pesam mais), a credibilidade da fonte, quantos veículos cobriram e
a hora; esporte, celebridade e afins ficam de fora. Pesos e fontes ajustáveis em `config/temas_noticias.yaml` e
`config/fontes_noticias.yaml`.

### 🎓 Estudo e certificações
| Pedido | Comando | Exemplo |
|---|---|---|
| Painel de estudo e área ativa | `/academia` · `/area` | `/area CNPI` |
| Questões (com correção comentada) | `/questoes` | `/questoes renda fixa` |
| Simulado | `/simulado` | `/simulado mini` · `/simulado completo` |
| Flashcards (repetição espaçada) | `/flashcards` | — |
| Diagnóstico e plano de estudo | `/diagnostico` · `/plano` | `/plano 5` (horas/semana) |
| Aula curta / caso para treinar | `/aula` · `/caso` | `/aula duration` · `/caso aposentadoria` |
| Estudar com seus livros (com citação) | `/estudar` | `/estudar convexidade` |
| Mesa-redonda de autores | `/debate` | `/debate diversificação` |
| Pílula do dia | `/pilula` | — |

20 campos de finanças + certificações (CFP, CNPI, CEA, CFA…). Questões geradas pela IA passam por conferência de conta
e por revisão de outro modelo antes de entrar.

### 🤝 Assessoria do dia a dia (clientes sempre como CLI-XXX)
| Pedido | Comando | Exemplo |
|---|---|---|
| Dossiê para a próxima reunião | `/reuniao` | `/reuniao CLI-012` |
| Pós-reunião: áudio → resumo, decisões, tarefas | `/pos` | `/pos CLI-012` e mande o áudio |
| Responder objeção | `/objecao` | `/objecao meu gerente já cuida disso` |
| Explicar produto para um perfil | `/explicar` | `/explicar LCI para aposentada conservadora` |
| Rascunho de mensagem (com conferência de compliance) | `/mensagem` | `/mensagem WhatsApp CLI-012 vencimento do CDB` |
| Vencimentos das carteiras | `/vencimentos` | `/vencimentos 60` |
| Treinar com cliente simulado (com nota) | `/treino` | `/treino` · `/treino fim` (feedback) |

### 🧭 Planejamento financeiro (padrão CFP)
| Pedido | Comando |
|---|---|
| Ficha do cliente (pergunta aos poucos) | `/cliente CLI-021` |
| Planejamento completo (PDF + planilha) | `/planejamento CLI-021` |
| Aposentadoria (capital, aporte, Monte Carlo) | `/aposentadoria CLI-021` |
| Sucessão (meação, herança, ITCMD, liquidez) | `/sucessao CLI-021` |
| Tributário (completa × simplificada, PGBL, PF × PJ) | `/tributario CLI-021` |
| Proteção (vida, invalidez, reserva, saúde) | `/protecao CLI-021` |
| Empresário (PF × Simples × Presumido) | `/empresario CLI-021` |
| Simulador de patrimônio (4 perguntas + gráfico) | `/simular …` ou fale normal · Terminal `SIM` |

### 🏦 Fundos, FIIs e previdência (dados da CVM)
`/fundo Verde 30` · `/comparar_fundos A, B, C` · `/gestor Ibiuna` · `/fii HGLG11 KNRI11` ·
`/previdencia atual X, destino Y, saldo 300 mil` · `/alternativos FIDC`

### 🏭 Empresas listadas (uso interno — não é relatório de análise, Resolução CVM 20)
`/empresa WEGE3` (raio-X) · `/valuation WEGE3` (DCF com premissas rastreáveis, cenários, DCF reverso) ·
`/tese WEGE3 merece prêmio` (debate ou advogado do diabo) · `/setor WEGE3 RAPT4 TUPY3` · `/resultado WEGE3`

### 🧮 Análises, carteira e contas
| Pedido | Comando | Exemplo |
|---|---|---|
| Análise com relatório PDF + planilha (em segundo plano) | `/analise` | `/analise compare CDB 110% CDI e LCI 92% em 2 anos` |
| Diagnóstico de carteira (risco, stress, alocação, rebalanceamento com IR) | `/carteira` ou mande print/planilha | `/carteira CLI-012 moderado: CDB R$ 120 mil; PETR4 1000` |
| Contas com memória de cálculo | `/calc` | `/calc parcela de 300 mil a 1% a.m. em 360 meses` |

Os números são sempre calculados em Python, com fonte; a IA só interpreta e escreve.

### 🗂️ Organização
`/tarefa` · `/tarefas` · `/feito 3` · `/adiar 3 sexta` · `/hoje` · `/nota texto #tag` · `/notas busca` ·
`/meta estudar 5 horas por semana` · `/metas` · `/revisao` · `/evento quinta às 15h reunião` (Google Agenda)

### 🧭 Carreira
`/carreira` (plano e certificações) · `/diario <tese>` (diário de teses com revisão e calibração) · `/portfolio`
(portfólio de análises em PDF) · `/entrevista [cargo]` (simulação com feedback) · `/radar [dias]` (normas novas)

### ✍️ Conteúdo (sai sempre como RASCUNHO, com disclaimer e fontes)
`/pauta [tema]` · `/roteiro reels|youtube|carrossel|fio|artigo <tema>` · `/fio <tema>` · `/ideia` · `/ideias` ·
`/conferir <seu texto>` (compliance + números conferidos)

### 🧠 Memória
Ele aprende sozinho com as conversas (preferências, objetivos, rotina, estudo, clientes por código) e lembra no Telegram
e no Terminal. `/memoria` (ver) · `/memoria buscar <tema>` · `/memoria esquecer <nº>` · `/memoria mudar <nº> <texto>` ·
`/memoria hoje` (tudo o que aconteceu no dia) · `/memoria conversas` · `/memoria exportar` · `/lembrar <fato>`

### ⚙️ Conversa e sistema
`/novo` (novo assunto) · `/agenda` (lembretes e rotinas) · `/sair` (fecha treino, entrevista ou pós-reunião) ·
`/ajuda` · `/start` (botões rápidos). No Terminal, a aba **CONFIGURAÇÕES** liga/desliga o bot, guarda as chaves,
conecta o Google Agenda e tem o botão **Verificar tudo**.

---

## 4. Proteções (o que ele nunca faz)

- **Dado pessoal não sai do seu computador.** Mensagem com CPF, telefone ou e-mail **não é enviada à IA**: ele avisa e
  pede para reescrever com o código CLI-XXX. CNPJ de fundo/empresa pode (é público). A memória também recusa dado pessoal.
- **Ações que apagam ou mexem fora do Quíron pedem ✅**: apagar tarefa, alerta ou memória, cancelar rotina, criar
  evento na Google Agenda, fechar tese, apagar cliente (LGPD) e mudar ficha com dados de reunião. Pelos comandos
  diretos (ex.: `/feito 3`) é na hora, porque foi você quem mandou.
- **Texto de fora não manda nele**: o que vem de notícias, páginas e documentos é tratado como informação; se algum
  texto “mandar” ele fazer algo, ele ignora e avisa você.
- **Compliance automático**: texto para cliente sai como RASCUNHO; análise com recomendação de ação ganha o rodapé
  “Uso interno — não constitui relatório de análise”; conteúdo público leva disclaimer.
- **Nunca trava o bot**: ferramenta que não responde em 3 min é interrompida e ele avisa; resposta que passa de 7 min
  é cortada com explicação (análises pesadas rodam em segundo plano).
- Nunca se conecta à EQI nem a corretora, nunca executa operação financeira e não fala com clientes.
- `/esquecer CLI-XXX` apaga tudo de um cliente (ficha, carteiras, relatórios, reuniões, conversas, memória, tarefas).

## 5. Limites de hoje (bom saber)

- **Cota gratuita da IA**: o Gemini mais novo dá ~20 pedidos/dia; depois ele passa para outros modelos gratuitos
  (Groq). Respostas podem ficar um pouco mais simples no fim do dia. As funções diretas não gastam cota.
- **Uma mensagem por vez**: enquanto ele pensa numa pergunta longa, a próxima espera na fila.
- **O bot só funciona com o PC (ou o servidor) ligado.** Até ir para o host 24h, lembretes que venceram com o PC
  desligado chegam quando ele religar; mensagens que você mandou com ele desligado há mais de 6 h são ignoradas.
- **Arquivos**: carteira por print ou planilha; PDF de livro vai pelo Acervo do Terminal; PDF de extrato ainda não.
- **Dados**: só fontes públicas e gratuitas. Cotação intradiária pode ter atraso de 15 min; fundos dependem da CVM
  (atualização diária/mensal).
- Clientes da EQI só como CLI-XXX, digitados por você; nomes reais só no cofre da versão offline.

---

## 6. Funções que complementariam o Quíron hoje

Ordenadas pelo retorno para o seu dia a dia de assessor. Todas são gratuitas e respeitam as regras (sem EQI, sem dado
pessoal na nuvem, sem X/Twitter).

### Prioridade alta — pouco esforço, ganho imediato
1. **Dossiê automático antes de cada reunião.** O Quíron já lê sua Google Agenda: 1 h antes de um evento com
   “CLI-XXX” no título, ele manda o `/reuniao` pronto; quando o evento termina, lembra “manda o áudio para o `/pos`”.
   Fecha o ciclo reunião → registro sem você lembrar de nada.
2. **Integração com o seu CRM (Fase 18, já desenhada e adiada).** Etapa do funil, faixas de patrimônio, aplicações e
   próxima revisão entram no Quíron só pelo código CLI-XXX → vencimentos, dossiê e “clientes sem contato há 60 dias” no
   briefing. Falta você responder as 3 perguntas do `docs/11-INTEGRACOES.md`.
3. **Painel de produção comercial.** Registrar captação, receita comissionada e reuniões por mês (“captei 300 mil
   hoje”), com meta, ritmo esperado e projeção do mês — usando as metas que já existem. É o número que mais importa
   para quem é comissionado.
4. **Leitura de extrato/posição em PDF.** Hoje ele lê print e planilha; o PDF de posição consolidada de corretora é o
   formato mais comum que o cliente manda. Leitura local (no PC), com nome e documento ocultados antes de qualquer IA.

### Prioridade média — mais trabalho, ganho forte
5. **Vigia dos fundos dos clientes.** Pela CVM: avisar se um fundo das carteiras guardadas trocou de gestor, mudou a
   taxa, fechou para captação ou entrou em come-cotas — motivo pronto para ligar para o cliente.
6. **Ofertas públicas da semana.** CRA, CRI, debêntures e ofertas de ações registradas na CVM (dados abertos), filtradas
   pelo perfil dos seus clientes, com resumo de risco. Bom para prospecção e para conteúdo.
7. **Calendário de proventos e eventos da watchlist.** Data-com, pagamento de dividendos/JCP, resultados e assembleias
   das ações e FIIs que você acompanha, no briefing e no `/hoje`.
8. **Relatório mensal para o cliente (RASCUNHO).** PDF de uma página por CLI-XXX: carteira, rentabilidade contra o CDI,
   vencimentos e próximos passos — você revisa e envia.

### Prioridade baixa — quando o básico estiver rodando no servidor
9. **Resumo de vídeos e podcasts** (transcrição pela API oficial do YouTube) para estudo e para pautas de conteúdo.
10. **Leitura de lâmina de COE/oferta em PDF** → resumo de riscos e cenários em linguagem de cliente.
11. **Calculadora de receita (ROA) por produto/cliente**, para decidir onde dedicar tempo.

**Sugestão de próximo passo:** começar pelo item 1 (dossiê automático), que aproveita o que já existe, e pelo item 3
(produção comercial). O item 2 depende das suas respostas sobre o CRM.
