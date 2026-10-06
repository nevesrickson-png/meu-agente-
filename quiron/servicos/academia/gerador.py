"""Gera questões e flashcards no estilo do exame, ancorados no edital (tópico) e, se houver, na biblioteca.

Rigor:
- cada questão aponta para um código de tópico do edital;
- questões com conta trazem `verificacao` (expressão aritmética) que o Python calcula: se não bater com a
  alternativa correta, a questão é descartada (o modelo nunca "inventa" o número);
- tributação usa `config/regras_mercado.yaml` (com o aviso quando o bloco não foi verificado);
- o Rickson pode anular qualquer questão com erro (botão ⚠ no Telegram).
"""

from __future__ import annotations

import ast
import json
import logging
import operator
import random
import re
from dataclasses import dataclass, replace
from typing import Any

from quiron.nucleo import cerebro
from quiron.nucleo.config import PASTA_CONFIG, Config, carregar_config
from quiron.servicos.academia import edital
from quiron.servicos.academia.banco import LETRAS, Banco

MODULOS_COM_REGRAS = {2, 3, 4, 6, 7}  # CFP: módulos onde alíquotas/regras de mercado aparecem
CAMPOS_COM_REGRAS = {"RENDA_FIXA", "RENDA_VARIAVEL", "DERIVATIVOS", "FUNDOS", "PREVIDENCIA", "PLANEJAMENTO",
                     "TRIBUTACAO", "SUCESSAO", "INTERNACIONAL", "CARTEIRAS"}


def _area(cert: str):
    from quiron.servicos import areas

    return areas.obter(cert)


def descricao_area(cert: str) -> str:
    a = _area(cert)
    if cert == "CFP":
        return "do exame CFP® da Planejar"
    if a and a.tipo == "certificacao":
        return f"no estilo da prova da certificação {a.nome}"
    nome = a.nome if a else cert
    return (f"de {nome} para profissionais do mercado financeiro brasileiro (nível das certificações CFP, CNPI e CFA, "
            "com foco em aplicação prática)")


def usa_regras(cert: str, modulo: int) -> bool:
    if cert == "CFP":
        return modulo in MODULOS_COM_REGRAS
    return cert in CAMPOS_COM_REGRAS or (_area(cert) is not None and _area(cert).tipo == "certificacao")


def sistema(cert: str = "CFP") -> str:
    return SISTEMA.replace("{AREA}", descricao_area(cert))


SISTEMA = (
    "Você é professor e elaborador de questões {AREA} (Brasil). Escreve em português do Brasil, "
    "com legislação e mercado brasileiros vigentes. Questões objetivas de 4 alternativas (A–D), uma só correta, "
    "distratores plausíveis (erros comuns de quem estudou pouco), nível de aplicação/análise "
    "(mini-casos realistas, não só definição decorada). Nunca use nomes de pessoas reais.\n"
    "Regras de qualidade: (1) a resposta certa tem de ser defensável por regra, lei ou conceito objetivo — nada de "
    "'melhor alocação' com percentuais arbitrários; (2) nunca invente normas, faixas, siglas ou 'diretrizes' de órgãos "
    "(Bacen, CVM, ANS, Susep) que não existam; se citar lei, cite só as que você tem certeza; (3) cada distrator tem de "
    "estar claramente errado para quem domina o assunto; (4) se a regra depende de condição (prazo, nº de cotistas, "
    "regime), o enunciado deve trazer o dado necessário."
)

FORMATO = """Responda SOMENTE com JSON neste formato:
{"questoes": [{"enunciado": "...", "alternativas": ["...", "...", "...", "..."], "correta": "A|B|C|D",
  "explicacao": "por que a correta está certa e por que cada errada está errada (curto)",
  "dificuldade": "facil|media|dificil", "subtopico": "código mais específico do edital, se houver",
  "verificacao": "SÓ se houver conta: expressão aritmética em Python (números, + - * / ** ( ), round) cujo resultado é o valor da alternativa correta; senão deixe vazio"}]}"""


# ---------------------------------------------------------------- verificação aritmética segura
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def calcular(expressao: str) -> float:
    """Calcula uma expressão aritmética simples sem `eval` (só números, operadores e round/abs/min/max)."""
    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 1000:
                raise ValueError("expoente grande demais")
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {"round", "abs", "min", "max"} \
                and not n.keywords:
            args = [ev(a) for a in n.args]
            return float({"round": lambda *a: round(a[0], int(a[1]) if len(a) > 1 else 0), "abs": abs, "min": min,
                          "max": max}[n.func.id](*args))
        raise ValueError(f"elemento não permitido: {type(n).__name__}")

    return ev(ast.parse(expressao.replace("^", "**"), mode="eval"))


def numeros(texto: str) -> list[float]:
    """Números de um texto em formato brasileiro (R$ 1.234,56 · 12,5% · 1234.5)."""
    achados = []
    for m in re.finditer(r"-?\d[\d.]*(?:,\d+)?|-?\d+(?:\.\d+)?", texto):
        s = m.group()
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        try:
            achados.append(float(s))
        except ValueError:
            pass
    return achados


def confere_conta(alternativa: str, expressao: str, tolerancia: float = 0.01) -> bool:
    valor = calcular(expressao)
    for m in re.finditer(r"-?\d[\d.,]*\d|-?\d", alternativa):
        n = numeros(m.group())
        if not n:
            continue
        pct = alternativa[m.end():m.end() + 2].lstrip().startswith("%")
        for candidato in (valor, valor * 100) if pct else (valor,):  # 0,125 escrito como 12,5% (só com o sinal de %)
            if abs(n[0] - candidato) <= max(abs(candidato) * tolerancia, 0.011):
                return True
    return False


# ---------------------------------------------------------------- contexto
def _trechos_biblioteca(consulta: str, n: int = 3, area: str | None = None) -> list[tuple[str, str]]:
    """(texto, citação) dos livros/apostilas do Rickson — primeiro da pasta da área no acervo, depois de todo o acervo.
    Só consulta se a biblioteca já tiver algo (evita baixar o modelo de embeddings à toa)."""
    try:
        from quiron.servicos.biblioteca.indice import Indice

        indice = Indice()
        if not indice.catalogo():
            return []
        achados = indice.buscar(consulta, n, area=area) if area else []
        if len([r for r in achados if r.semelhanca >= 0.35]) < 2:
            achados = indice.buscar(consulta, n)
        return [(r.texto[:900], r.citacao) for r in achados if r.semelhanca >= 0.35]
    except Exception:  # noqa: BLE001 — biblioteca é um extra; sem ela a questão sai do edital
        logging.exception("biblioteca indisponível para o gerador")
        return []


def _regras_texto() -> str:
    arq = PASTA_CONFIG / "regras_mercado.yaml"
    return arq.read_text(encoding="utf-8")[:3500] if arq.exists() else ""


def contexto_topico(codigo: str, cert: str = "CFP") -> dict[str, Any]:
    t = edital.topico(codigo, cert)
    if not t:
        raise KeyError(f"tópico {codigo} não existe no edital de {cert}")
    partes = codigo.split(".")
    cadeia = [edital.topico(".".join(partes[:i]), cert) for i in range(2, len(partes))]
    return {"topico": t, "cadeia": [c["titulo"] for c in cadeia if c],
            "filhos": [f"{f['codigo']} {f['titulo']}" for f in edital.filhos(codigo, cert)][:25]}


def montar_pedido(codigo: str, n: int, cert: str = "CFP", evitar: list[str] | None = None,
                  trechos: list[tuple[str, str]] | None = None) -> str:
    ctx = contexto_topico(codigo, cert)
    t = ctx["topico"]
    linhas = [f"Crie {n} questão(ões) inéditas {descricao_area(cert)}.",
              f"Módulo {t['modulo']} — {t['modulo_titulo']}.",
              f"Tópico do programa {t['codigo']}: {t['titulo']}."]
    if ctx["cadeia"]:
        linhas.append("Dentro de: " + " › ".join(ctx["cadeia"]))
    if t.get("itens"):
        linhas.append("Itens do edital: " + "; ".join(t["itens"]))
    if ctx["filhos"]:
        linhas.append("Subtópicos (varie entre eles e informe o código em 'subtopico'):\n" + "\n".join(ctx["filhos"]))
    if trechos:
        linhas.append("Trechos do material do Rickson (use se ajudar; cite em 'explicacao' como 'Fonte: …'):\n" +
                      "\n---\n".join(f"{c}\n{x}" for x, c in trechos))
    if usa_regras(cert, t["modulo"]):
        linhas.append("Regras de mercado/tributárias do Quíron (use estas alíquotas; se um bloco estiver com "
                      "verificado_em vazio, prefira questões conceituais a cálculos com ele):\n" + _regras_texto())
    if evitar:
        linhas.append("NÃO repita estas questões já existentes:\n- " + "\n- ".join(e[:160] for e in evitar[-15:]))
    linhas.append(FORMATO)
    return "\n\n".join(linhas)


def _json(texto: str) -> dict[str, Any]:
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini < 0 or fim < 0:
        raise ValueError("resposta sem JSON")
    return json.loads(texto[ini:fim + 1])


def validar(item: dict[str, Any], codigo: str, cert: str = "CFP") -> tuple[dict[str, Any] | None, str]:
    """Confere estrutura e conta. Devolve (questão normalizada, motivo da recusa)."""
    alts = [str(a).strip() for a in item.get("alternativas") or []]
    alts = [re.sub(r"^[A-Da-d][\)\.\-:]\s*", "", a) for a in alts]
    letra = str(item.get("correta", "")).strip().upper()[:1]
    if len(alts) != 4 or len(set(alts)) != 4 or letra not in LETRAS or not str(item.get("enunciado", "")).strip():
        return None, "estrutura inválida"
    correta = LETRAS.index(letra)
    verif = str(item.get("verificacao") or "").strip()
    if verif:
        try:
            if not confere_conta(alts[correta], verif):
                return None, f"conta não confere ({verif} ≠ alternativa {letra})"
            if outras := [LETRAS[i] for i, a in enumerate(alts) if i != correta and confere_conta(a, verif)]:
                return None, f"a conta também bate com a alternativa {', '.join(outras)} (questão ambígua)"
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as e:
            return None, f"verificação inválida ({e})"
    sub = str(item.get("subtopico") or "").strip()
    topico = sub if sub.startswith(codigo) and edital.topico(sub, cert) else codigo
    dif = str(item.get("dificuldade") or "media").lower()
    return {"enunciado": item["enunciado"].strip(), "alternativas": alts, "correta": correta,
            "explicacao": str(item.get("explicacao") or "").strip() + (f"\n🧮 Conta conferida em Python: {verif}" if verif else ""),
            "dificuldade": dif if dif in {"facil", "media", "dificil"} else "media", "topico": topico}, ""


REVISOR = (
    "Você é revisor técnico de questões {AREA} (Brasil), rigoroso com legislação, tributação e matemática "
    "financeira vigentes. Resolva cada questão por conta própria e aponte qualquer erro de conteúdo, ambiguidade "
    "ou mais de uma alternativa defensável."
)


def _provedor(modelo: str) -> str:
    return modelo.split("/", 1)[0]


def _config_invertida(config: Config | None, modelo_usado: str) -> Config:
    """Segunda opinião: o revisor começa pelos modelos de OUTRO provedor (Gemini revisa o Groq e vice-versa)."""
    config = config or carregar_config()
    outros = [m for m in config.modelos if _provedor(m) != _provedor(modelo_usado)]
    mesmos = [m for m in config.modelos if _provedor(m) == _provedor(modelo_usado) and m != modelo_usado]
    return replace(config, ordem=(*outros, *mesmos, modelo_usado))


def _config_gerador(config: Config | None) -> Config:
    """O gerador começa pelo modelo RESERVA (Groq): poupa a cota grátis do Gemini para o dia a dia e deixa o
    Gemini livre para ser o revisor independente."""
    config = config or carregar_config()
    return replace(config, ordem=(config.llm_reserva, *[m for m in config.modelos if m != config.llm_reserva]))


@dataclass
class Revisao:
    motivo: str  # '' = aprovada
    revisor: str = ""

    @property
    def aprovada(self) -> bool:
        return not self.motivo


def revisar(questoes: list[dict[str, Any]], modelo_gerador: str, config: Config | None = None,
            cert: str = "CFP", **extras: Any) -> list[Revisao]:
    """Revisor independente: resolve sozinho, depois confere gabarito e coerência da explicação com o enunciado."""
    blocos = []
    for i, q in enumerate(questoes, 1):
        alts = "\n".join(f"{LETRAS[j]}) {a}" for j, a in enumerate(q["alternativas"]))
        blocos.append(f"Questão {i}:\n{q['enunciado']}\n{alts}\n[gabarito proposto: {LETRAS[q['correta']]}]\n"
                      f"[explicação proposta: {q['explicacao']}]")
    pedido = ("Para cada questão: (1) resolva você mesmo ANTES de olhar o gabarito proposto e registre em "
              "'resposta_propria'; (2) confira se o gabarito está certo pela legislação vigente; (3) confira se a "
              "explicação é coerente com os dados do enunciado (números, condições, prazos) e se só uma alternativa "
              "é defensável.\n\n" + "\n\n".join(blocos) +
              '\n\nResponda SOMENTE com JSON: {"revisoes": [{"n": 1, "resposta_propria": "A|B|C|D", '
              '"problemas": "vazio se estiver tudo certo; senão descreva o erro"}]}')
    try:
        r = cerebro.perguntar(pedido, sistema=REVISOR.replace("{AREA}", descricao_area(cert)), config=_config_invertida(config, modelo_gerador),
                              temperatura=0, max_tokens=16000, response_format={"type": "json_object"}, **extras)
        revisoes = {int(x.get("n", 0)): x for x in _json(r.texto).get("revisoes") or []}
    except (cerebro.CerebroIndisponivel, ValueError, json.JSONDecodeError) as e:
        return [Revisao(f"revisão indisponível ({type(e).__name__})")] * len(questoes)
    saida = []
    for i, q in enumerate(questoes, 1):
        rv = revisoes.get(i) or {}
        resp = str(rv.get("resposta_propria") or rv.get("resposta") or "").strip().upper()[:1]
        prob = str(rv.get("problemas") or "").strip()
        if prob and prob.lower().strip(" .") not in {"nenhum", "vazio", "-", "n/a", "nada", "ok"}:
            saida.append(Revisao(f"revisor apontou: {prob[:200]}", r.modelo))
        elif resp != LETRAS[q["correta"]]:
            saida.append(Revisao(f"revisor marcou {resp or '?'} e o gabarito era {LETRAS[q['correta']]}", r.modelo))
        else:
            saida.append(Revisao("", r.modelo))
    return saida


def gerar_questoes(codigo: str, n: int = 3, cert: str = "CFP", banco: Banco | None = None,
                   config: Config | None = None, **extras: Any) -> dict[str, Any]:
    """Gera, valida e grava questões de um tópico. Devolve {'gravadas': [ids], 'recusadas': [motivos]}."""
    banco = banco or Banco()
    mock_revisao = extras.pop("mock_revisao", None)  # nos testes: resposta simulada do revisor
    t = edital.topico(codigo, cert)
    if not t:
        raise KeyError(f"tópico {codigo} não existe no edital de {cert}")
    trechos = _trechos_biblioteca(f"{t['titulo']} {' '.join(t.get('itens', []))}", area=cert)
    pedido = montar_pedido(codigo, n, cert, banco.enunciados(cert, codigo), trechos)
    # max_tokens alto: os modelos "pensantes" (Gemini) gastam parte dele raciocinando antes de responder
    r = cerebro.perguntar(pedido, sistema=sistema(cert), config=_config_gerador(config), temperatura=0.5, max_tokens=16000,
                          response_format={"type": "json_object"}, **extras)
    gravadas, recusadas = [], []
    try:
        itens = _json(r.texto).get("questoes") or []
    except (ValueError, json.JSONDecodeError) as e:
        return {"gravadas": [], "recusadas": [f"resposta ilegível: {e}"], "modelo": r.modelo}
    fontes = sorted({c for _, c in trechos})
    validas = []
    for item in itens[:n]:
        q, motivo = validar(item, codigo, cert)
        if q:
            validas.append(q)
        else:
            recusadas.append(motivo)
    motivos = revisar(validas, r.modelo, config, cert, **({"mock_response": mock_revisao} if mock_revisao else {})) \
        if validas else []
    for q, rv in zip(validas, motivos):
        if not rv.aprovada:
            recusadas.append(rv.motivo)
            continue
        gravadas.append(banco.adicionar_questao(cert, t["modulo"], q["topico"], q["enunciado"], q["alternativas"],
                                                q["correta"], q["explicacao"], fontes, q["dificuldade"], "gerada", r.modelo,
                                                revisor=rv.revisor))
    return {"gravadas": gravadas, "recusadas": recusadas, "modelo": r.modelo}


def topicos_para_gerar(modulo: int, quantos: int, cert: str = "CFP", banco: Banco | None = None,
                       semente: int | None = None) -> list[str]:
    """Tópicos de nível 2 (ex.: 3.5.2) do módulo, priorizando os com menos questões; sorteio entre empates."""
    banco = banco or Banco()
    candidatos = [t["codigo"] for t in edital.topicos(cert, modulo=modulo) if t["codigo"].count(".") == 2] or \
                 [t["codigo"] for t in edital.topicos(cert, modulo=modulo) if t["codigo"].count(".") == 1]
    contagem = banco.contar_por_topico(cert, modulo)
    rnd = random.Random(semente)
    rnd.shuffle(candidatos)

    def total(c: str) -> int:
        return sum(v for k, v in contagem.items() if k == c or k.startswith(c + "."))

    candidatos.sort(key=total)
    return candidatos[:quantos]


# ---------------------------------------------------------------- flashcards
FORMATO_CARDS = """Responda SOMENTE com JSON: {"cards": [{"frente": "pergunta curta", "verso": "resposta curta e exata (até 3 linhas)"}]}"""


def gerar_flashcards(codigo: str, n: int = 5, cert: str = "CFP", banco: Banco | None = None,
                     config: Config | None = None, **extras: Any) -> list[int]:
    banco = banco or Banco()
    ctx = contexto_topico(codigo, cert)
    t = ctx["topico"]
    trechos = _trechos_biblioteca(t["titulo"], area=cert)
    pedido = "\n\n".join(filter(None, [
        f"Crie {n} flashcards {descricao_area(cert)} para memorizar o essencial do tópico {t['codigo']} — {t['titulo']} "
        f"(módulo {t['modulo']}: {t['modulo_titulo']}).",
        "Itens do edital: " + "; ".join(t.get("itens", [])) if t.get("itens") else "",
        "Subtópicos: " + "; ".join(ctx["filhos"][:15]) if ctx["filhos"] else "",
        "Material do Rickson:\n" + "\n---\n".join(f"{c}\n{x}" for x, c in trechos) if trechos else "",
        "Regras do Quíron:\n" + _regras_texto() if usa_regras(cert, t["modulo"]) else "",
        "Foque em conceitos, prazos, limites, alíquotas e fórmulas cobrados na prova.", FORMATO_CARDS]))
    r = cerebro.perguntar(pedido, sistema=sistema(cert), config=_config_gerador(config), temperatura=0.4, max_tokens=12000,
                          response_format={"type": "json_object"}, **extras)
    ids = []
    for c in (_json(r.texto).get("cards") or [])[:n]:
        frente, verso = str(c.get("frente", "")).strip(), str(c.get("verso", "")).strip()
        if frente and verso:
            ids.append(banco.adicionar_card(cert, t["modulo"], codigo, frente, verso, sorted({x for _, x in trechos})))
    return ids
