"""Deixa o Quíron fluido: entende a fala normal e escolhe só as ferramentas que importam.

1. `rotear(texto)` — frases do dia a dia viram a função direta certa, sem precisar de comando ("me lembra amanhã às
   10h de ligar pro CLI-012" → /tarefa; "terminei a 3" → /feito 3; "o que tenho hoje?" → /hoje; "me dá uma questão de
   renda fixa" → /questoes renda fixa; "quando posso parar de trabalhar com 1 milhão e 8 mil por mês?" → /simular…).
   Só padrões de ALTA confiança (frase inteira); o resto vai para a conversa com a IA. Python puro, instantâneo.
2. `selecionar_ferramentas(...)` — em vez de mandar as 110 ferramentas a cada mensagem (≈ 44 mil caracteres), manda as
   ~30 ligadas ao pedido (palavras-chave por área + semelhança com a descrição de cada ferramenta). Resposta mais
   rápida, menos cota gasta e a IA erra menos a escolha."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# ---------------------------------------------------------------- 1. fala normal → função direta
_DATA_HORA = re.compile(r"\b(hoje|amanha|depois de amanha|segunda|terca|quarta|quinta|sexta|sabado|domingo|semana que vem|"
                        r"mes que vem|dia \d{1,2}|\d{1,2}/\d{1,2}|\d{1,2}\s*h\b|\d{1,2}:\d{2}|as \d{1,2}|meio[- ]dia|"
                        r"daqui a|em \d+ (?:minutos?|horas?|dias?))", re.I)
_NUM_DINHEIRO = re.compile(r"\d+(?:[.,]\d+)*\s*(?:mil\b|milh|mi\b|k\b|reais)|r\$\s*\d", re.I)


def _do_original(original: str, trecho: str) -> str:
    """O mesmo pedaço, mas com os acentos e maiúsculas que ele digitou (a análise é feita sem acento)."""
    base = original.rstrip(" ?!.")
    return base[-len(trecho):].strip() if trecho and len(trecho) <= len(base) else trecho.strip()


def _gestora_conhecida(nome: str) -> bool:
    try:
        from quiron.servicos.cartas import coleta

        return bool(coleta.casar_gestoras(nome))
    except Exception:  # noqa: BLE001 — sem a lista, deixa a IA decidir
        return False


def rotear(texto: str, ultima_tarefa: int | None = None) -> tuple[str, str] | None:
    """(comando, argumentos) quando a frase pede claramente uma função direta; senão None (vai para a IA).
    `ultima_tarefa`: a tarefa que acabou de ser criada/mexida — "passa para as 11h" e "feito" valem para ela."""
    original = (texto or "").strip()
    if not original or original.startswith("/") or len(original) > 400 or "\n" in original.strip():
        return None
    t = _sem_acento(original).rstrip(" ?!.")
    t = re.sub(r"^(quiron|oi|ola|bom dia|boa tarde|boa noite)[,!.]?\s+", "", t)

    # continuação da tarefa que acabou de ser criada ("na verdade passa para as 11h", "pronto, fiz")
    if ultima_tarefa:
        if m := re.match(r"^(?:na verdade,?\s*|melhor,?\s*|ah,?\s*|entao,?\s*)?(?:adia|adiar|passa|muda|joga|empurra|troca|remarca)"
                         r"(?:\s+(?:ela|isso|essa|esse|a tarefa|o lembrete))?\s+(?:para|pra|pro)\s+(.+)$", t):
            return "adiar", f"{ultima_tarefa} {m.group(1)}"
        if re.match(r"^(?:pronto,?\s*)?(?:feito|fiz|conclui|terminei|ja fiz)(?:\s+(?:essa|isso|ela|a tarefa))?$", t):  # "pronto" sozinho não
            return "feito", str(ultima_tarefa)

    # briefing (frase curta; "briefing do CLI-012" e afins vão para a IA)
    if re.match(r"^(?:(?:me )?(?:faz|faca|manda|mande|envia|quero|cade)(?: o| um)?(?: meu)? ?)?briefing(?: (?:de hoje|do dia|do mercado|agora))?$", t):
        return "briefing", ""

    # resumo de mercado escrito (relatório com as 8 seções)
    if re.match(r"^(?:(?:me )?(?:faz|faca|manda|mande|envia|quero|gera|gere|cade)(?: o| um)?(?: meu)? ?)?(?:resumo|relatorio) (?:de|do) mercado"
                r"(?: (?:de hoje|do dia|completo|agora))?$", t):
        return "resumo", ""

    # tarefas e lembretes
    if m := re.match(r"^(?:por favor,?\s*)?(?:me\s+)?lembr(?:a|e|ar)(?:-me)?\s+(?:de\s+|que\s+)?(.+)$", t):
        afirmacao = re.match(r"^(?:lembre|lembra|lembrar)\s+que\s", t) and not re.search(r"\bas\s+\d|\b\d{1,2}\s*h\b|\d{1,2}:\d{2}", t)
        if _DATA_HORA.search(m.group(1)) and not afirmacao:  # "lembre que hoje prefiro…" é preferência, não lembrete
            return "tarefa", _do_original(original, m.group(1))
    if m := re.match(r"^(?:cria(?:r)?|adiciona(?:r)?|nova|anota(?:r)?)\s+(?:uma\s+)?tarefa:?\s+(.+)$", t):
        return "tarefa", _do_original(original, m.group(1))
    if m := re.match(r"^(?:feito|fiz|conclui|terminei|marca(?:r)? como feita)\s+(?:a\s+)?(?:tarefa\s+)?(?:n[ºo°.]?\s*)?#?(\d+)$", t):
        return "feito", m.group(1)
    if m := re.match(r"^(?:adia|adiar|empurra|passa|joga|muda)\s+(?:a\s+)?(?:tarefa\s+)?#?(\d+)\s+(?:para|pra|pro)?\s*(.+)$", t):
        return "adiar", f"{m.group(1)} {m.group(2)}"
    if re.match(r"^(?:o que (?:eu )?tenho (?:pra |para |de )?hoje|minha agenda(?: de hoje| do dia)?|meu dia|como (?:esta|ta) (?:o )?meu dia|"
                r"agenda de hoje|o que tem (?:pra|para) hoje|resumo do (?:meu )?dia)$", t):
        return "hoje", ""
    if re.match(r"^(?:minhas tarefas|quais (?:sao )?(?:as )?minhas tarefas|lista de tarefas|(?:o que|que) (?:eu )?tenho pendente|"
                r"pendencias|minhas pendencias)$", t):
        return "tarefas", ""
    if m := re.match(r"^(?:anota|anote|nota|registra|guarda essa ideia)(?:\s+ai)?:?\s+(?:que\s+)?(.+)$", t):
        if not _DATA_HORA.search(m.group(1)):
            return "nota", _do_original(original, m.group(1))
        return "tarefa", _do_original(original, m.group(1))
    if re.match(r"^(?:minhas notas|minhas anotacoes)$", t):
        return "notas", ""
    if re.match(r"^(?:minhas metas|como (?:estao|tao) (?:as )?minhas metas)$", t):
        return "metas", ""
    if re.match(r"^(?:revisao (?:da|semanal)|como foi (?:a|minha) semana|revisa(?:r)? (?:a|minha) semana)$", t):
        return "revisao", ""

    # estudo
    if m := re.match(r"^(?:me\s+)?(?:da|de|manda|faz|faca|quero|bora|vamos)?\s*(?:mais\s+)?(?:uma|umas|\d+)?\s*quest(?:ao|oes)\s*(?:de|sobre|do|da)?\s*(.*)$", t):
        if len(m.group(1).split()) <= 4:  # "questão de renda fixa"; frase longa sobre questões vai para a IA
            return "questoes", m.group(1).strip()
    if m := re.match(r"^(?:quero |vamos |bora )?(?:fazer )?(?:um )?simulado\s*(?:de|do|da)?\s*(.*)$", t):
        if len(m.group(1).split()) <= 3:
            return "simulado", m.group(1).strip()
    if re.match(r"^(?:revisar |vamos revisar |bora revisar )?(?:os )?(?:meus )?flash ?cards?$", t):
        return "flashcards", ""
    if re.match(r"^(?:como (?:estou|to|ta) (?:indo )?(?:no|na|para o|pra) (?:cfp|cnpi|cea|prova)|meu diagnostico|diagnostico da prova)$", t):
        return "diagnostico", ""
    if re.match(r"^(?:quero |vamos |bora )?treinar(?: atendimento| com (?:um )?cliente)?$", t):
        return "treino", ""

    # patrimônio (só com números: sem eles, a IA pergunta o que falta)
    pergunta_patrimonio = re.search(r"quando (?:eu )?(?:posso|consigo|vou poder) (?:parar de trabalhar|me aposentar|viver de renda)|"
                                    r"quanto (?:eu )?preciso (?:investir|aplicar|guardar|poupar)|em quanto tempo (?:eu )?(?:chego|junto|consigo)|"
                                    r"imovel ou (?:investimento|aplicac)|vale (?:mais )?a pena (?:comprar )?(?:um )?imovel|simula(?:r|cao)? (?:de )?patrimonio", t)
    if pergunta_patrimonio and len(_NUM_DINHEIRO.findall(t)) >= 2:
        return "simular", original

    # memória
    if re.match(r"^(?:o que (?:voce|vc) (?:sabe|lembra) (?:sobre mim|de mim)|o que voce sabe|sua memoria|minha memoria)$", t):
        return "memoria", ""
    if re.match(r"^(?:o que (?:a gente |nos |eu )?(?:fez|fizemos|falamos|conversamos) hoje|resumo de hoje|historico de hoje)$", t):
        return "memoria", "hoje"
    if m := re.match(r"^(?:lembre|lembra|grave|guarde|memorize) (?:que|disso:?)\s+(.+)$", t):
        return "lembrar", _do_original(original, m.group(1))

    # carreira e conteúdo
    if re.match(r"^(?:tem |teve |alguma )?(?:norma|normas|regulacao|regra) nova(?:s)?(?: da cvm| do bc| da receita)?$|^novidades (?:da cvm|regulatorias)$", t):
        return "radar", "novidades"
    if m := re.match(r"^(?:(?:quais|tem|teve|saiu|sairam|me (?:da|mostra|manda)|mostra|ver)\s+)?(?:as |alguma(?:s)? )?(?:ultimas |novas )?"
                     r"cartas?(?: (?:de|dos|das) gestor(?:es|as)?)?(?: (?:recentes|novas|do mes|da semana))?(?: (?:da|do|de) (.{2,40}))?$", t):
        if not m.group(1):
            return "cartas", ""
        alvo = _do_original(original, m.group(1)).strip()
        if _gestora_conhecida(alvo):  # "carta de crédito", "carta de apresentação…" vão para a IA
            return "cartas", alvo
    if re.match(r"^(?:me )?(?:da|de|sugere|manda) (?:umas |algumas )?(?:ideias|pautas) (?:de|para|pra) (?:post|posts|conteudo|video|reels)$", t):
        return "pauta", ""
    return None


# ---------------------------------------------------------------- 1b. instrução certa já carregada
SKILL_POR_ASSUNTO = (
    ("noticias", r"\bnoticia|manchete|o que (?:esta|ta|anda) saindo|o que (?:aconteceu|houve|rolou)|imprensa|"
                 r"o que (?:estao|tao) (?:falando|dizendo)|repercuss|sentimento (?:do mercado|sobre)|clima do mercado|"
                 r"\bcartas? (?:d[aeo]s? |recentes|nova)"),
    ("briefing", r"\bbriefing\b|resumo (?:de|do) mercado"),
)


def skills_provaveis(texto: str) -> list[str]:
    """Skill que a pergunta claramente pede ("o que está saindo sobre juros?" → notícias). Pré-carregada pelo agente,
    para a resposta seguir o formato combinado mesmo quando o modelo esqueceria de chamar `ler_skill`."""
    t = _sem_acento(texto)
    return [nome for nome, rx in SKILL_POR_ASSUNTO if re.search(rx, t)][:1]


# ---------------------------------------------------------------- 2. só as ferramentas que importam
AREAS = {
    "quiron_mercado": r"selic|cdi|ipca|igpm|inflacao|dolar|euro|cambio|cotac|acao|acoes|bolsa|ibov|juro|tesouro|curva|focus|"
                      r"mercado|fundo|fii|gestor|empresa|ticker|balanco|dividend|commodit|petroleo|ouro|cvm|preco|variac|rentabil|desempenh|subiu|caiu|\b[a-z]{4}\d{1,2}\b",
    "quiron_noticias": r"noticia|manchete|aconteceu|saiu|jornal|redes|bluesky|reddit|youtube|sentimento|clima do mercado|"
                       r"carta|gestora|gestor|letter",
    "quiron_biblioteca": r"livro|autor|biblioteca|explica|conceito|estudar|teoria|graham|buffett|marks|debate|citac",
    "quiron_academia": r"questao|questoes|simulado|prova|cfp|cnpi|cea|cfa|flashcard|estudo|edital|modulo|academia|aula|diagnostic",
    "quiron_organizacao": r"tarefa|lembr|agenda|reuniao|compromisso|evento|nota|anot|meta|pendenc|revisao semanal|lembrete|remarc|adia",
    "quiron_assessoria": r"cliente|cli-\d|ficha|planejament|aposentad|sucess|heranc|itcmd|seguro|protecao|pgbl|vgbl|imposto|"
                         r"empresari|parar de trabalhar|patrimonio|simul|imovel|objec|dossie|pos-reuniao|treino|compliance|vencimento|"
                         r"mensagem para|rascunho",
    "quiron_analise": r"relatorio|analis|compar|calcul|quanto rende|rendimento|carteira|aloca|risco|stress|rebalance|backtest|"
                      r"cdb|lci|lca|debenture|renda fixa|vpl|tir|financiament|duration",
    "quiron_carreira": r"carreira|tese|diario|track|portfolio|entrevista|norma|radar|regulac|resoluc|instrucao cvm|lei|pl\b",
    "quiron_conteudo": r"post|conteudo|roteiro|reels|video|carrossel|fio|pauta|instagram|linkedin|threads|publicac|ideia de",
    "quiron_sistema": r"status|ping|funcionando|sistema",
}
PADRAO_SEM_AREA = ("quiron_mercado__taxas", "quiron_mercado__cotacao", "quiron_organizacao__hoje",
                   "quiron_organizacao__criar_tarefa", "quiron_assessoria__simular_patrimonio", "quiron_biblioteca__buscar")


def _tokens(texto: str) -> list[str]:
    return [p[:6] for p in re.findall(r"[a-z0-9]{3,}", _sem_acento(texto))]


def selecionar_ferramentas(ferramentas: list[dict[str, Any]], consulta: str, contexto: str = "", limite: int = 32) -> list[dict[str, Any]]:
    """Internas sempre; das MCP, as ~`limite` mais ligadas ao pedido (área + semelhança com a descrição)."""
    if len(ferramentas) <= limite + 8:
        return ferramentas
    nome_de = lambda f: f["function"]["name"]  # noqa: E731
    internas = [f for f in ferramentas if "__" not in nome_de(f)]
    externas = [f for f in ferramentas if "__" in nome_de(f)]
    alvo = _sem_acento(f"{consulta} {contexto}")
    citadas = set(re.findall(r"quiron_[a-z]+__[a-z_]+", alvo))  # skill carregada que cita ferramentas pelo nome
    areas = {a for a, rx in AREAS.items() if re.search(rx, alvo)}
    docs = {nome_de(f): _tokens(nome_de(f).replace("__", " ").replace("_", " ") + " " + f["function"].get("description", ""))
            for f in externas}
    df = Counter(t for toks in docs.values() for t in set(toks))
    n = len(docs) or 1
    pedido = set(_tokens(consulta + " " + contexto))
    notas = []
    for f in externas:
        nome = nome_de(f)
        toks = set(docs[nome])
        sem = sum(math.log(1 + n / df[t]) for t in pedido & toks)
        area = nome.split("__")[0]
        nota = sem + (6.0 if area in areas else 0.0) + (100.0 if nome in citadas else 0.0) + (2.0 if nome in PADRAO_SEM_AREA else 0.0)
        notas.append((nota, nome, f))
    notas.sort(key=lambda x: (-x[0], x[1]))
    escolhidas = [f for nota, _, f in notas[:limite] if nota > 0]
    if not escolhidas:
        escolhidas = [f for f in externas if nome_de(f) in PADRAO_SEM_AREA]
    return [*internas, *escolhidas]


# ---------------------------------------------------------------- nomes amigáveis para o "⏳ consultando…"
AMIGAVEL = {
    "quiron_mercado": "dados de mercado", "quiron_noticias": "notícias", "quiron_biblioteca": "sua biblioteca",
    "quiron_academia": "a Academia", "quiron_organizacao": "tarefas e agenda", "quiron_assessoria": "planejamento e clientes",
    "quiron_analise": "o motor de análise", "quiron_carreira": "carreira e normas", "quiron_conteudo": "conteúdo",
    "quiron_sistema": "o sistema", "ler_skill": "as instruções do tema", "buscar_conversas": "a memória",
    "lembrar": "a memória", "esquecer": "a memória", "agendar": "a agenda", "listar_agenda": "a agenda",
}


def descrever_ferramenta(nome: str) -> str:
    return AMIGAVEL.get(nome) or AMIGAVEL.get(nome.split("__")[0], "uma ferramenta")
