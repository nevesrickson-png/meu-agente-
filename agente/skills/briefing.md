# Skill: briefing do mercado (`/briefing`, rotina das 7h30)

**Quando usar:** "faça meu briefing", `/briefing`, rotina diária da manhã.

O briefing é montado em Python (`quiron/servicos/mercado/briefing.py`): formato fixo para o celular, números das
fontes oficiais com variação (▲/▼), as histórias que mais importam (já agrupadas e ordenadas por relevância), a agenda
da semana e as linhas "Para os clientes" (que já passaram por conferência: nenhum número fora dos dados).

## Passos
1. Chame `briefing` do servidor `quiron-mercado`.
2. **Entregue o texto exatamente como veio.** Não reescreva, não resuma, não troque a ordem, não coloque em bloco de
   código e não acrescente números.
3. Se ele pedir algo além (ex.: "e o que isso muda para o CLI-012?"), responda DEPOIS do briefing, em poucas linhas,
   usando as ferramentas para qualquer número novo.
4. Bloco "⚠️ … indisponível/desatualizado": mantenha o aviso; nunca complete de memória.
5. Sem recomendação de ativo específico (uso interno); texto para cliente só com a marca RASCUNHO.
