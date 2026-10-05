"""Pós-reunião: o Rickson grava um áudio (ou escreve) logo depois da reunião e o Quíron devolve resumo, decisões,
tarefas com prazo (viram lembretes) e sugestões para a ficha do cliente.

- O modelo só ESTRUTURA o que foi dito (e copia a expressão de prazo, ex.: "sexta que vem"); as datas são calculadas
  em `datas.py`. Sem modelo disponível, um leitor por regras faz o básico.
- CPF, telefone, e-mail e conta são ocultados antes de ir ao modelo. Cliente só como CLI-XXX.
- Fica guardado em `dados/reunioes/<CLI-XXX>/` (JSON + Markdown); `/esquecer` apaga.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from quiron.nucleo import cerebro
from quiron.nucleo.config import pasta_dados
from quiron.servicos.assessoria import compliance, datas
from quiron.servicos.carteira.leitura import mascarar_identificadores
from quiron.servicos.planejamento.ficha import codigo

# campos simples da ficha que uma reunião pode atualizar (o resto é conversa de planejamento)
CAMPOS_FICHA = {"idade": int, "uf": str, "estado_civil": str, "ocupacao": str, "renda_mensal_bruta": float,
                "despesas_mensais": float, "aporte_mensal": float, "idade_aposentadoria": int,
                "renda_desejada_aposentadoria": float, "perfil": str}
HORA_PADRAO = (9, 0)
OCUPACAO_SINONIMOS = {"medico": "profissional_liberal", "medica": "profissional_liberal", "advogado": "profissional_liberal",
                      "advogada": "profissional_liberal", "dentista": "profissional_liberal", "engenheiro": "clt",
                      "empresaria": "empresario", "aposentada": "aposentado", "servidora": "servidor", "funcionario_publico": "servidor",
                      "autonoma": "autonomo", "liberal": "profissional_liberal"}


def _sem_acento(t: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", t.lower().strip()) if unicodedata.category(c) != "Mn")

SISTEMA = (
    "Você organiza as anotações de um assessor de investimentos brasileiro logo depois de uma reunião com um cliente. "
    "Responda SÓ com JSON válido. Use apenas o que está no texto: não invente fatos, valores, produtos nem prazos. "
    "O cliente é identificado só pelo código; nunca escreva nomes de pessoas (troque por 'o cliente', 'a esposa', etc.). "
    "Se for transcrição de áudio, pode haver erro de reconhecimento de voz em termos de mercado (ex.: 'apodatabilidade' = "
    "portabilidade, '401' no lugar de CDI): corrija só quando for óbvio pelo contexto."
)
PEDIDO = """Data de hoje: {hoje} ({dia_semana}). Cliente: {cliente}.

Anotação/transcrição da reunião:
\"\"\"{texto}\"\"\"

Devolva este JSON:
{{"resumo": ["3 a 6 frases curtas com o essencial"],
 "decisoes": ["o que ficou decidido"],
 "tarefas": [{{"texto": "verbo no infinitivo + o quê (ex.: Enviar proposta de previdência)",
              "responsavel": "assessor" ou "cliente",
              "quando": "a expressão de prazo EXATAMENTE como foi dita (ex.: 'sexta que vem', 'dia 20', 'amanhã às 10h') ou null"}}],
 "proximo_contato": "expressão de prazo como foi dita, ou null",
 "ficha": [{{"campo": um de {campos}, "valor": "valor dito", "trecho": "frase de onde saiu"}}],
 "pontos_de_atencao": ["riscos, insatisfações, mudanças de vida, objeções que ficaram em aberto"],
 "perfil_sinais": ["sinais sobre tolerância a risco ou suitability"]}}"""

DIAS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


@dataclass
class Tarefa:
    texto: str
    responsavel: str = "assessor"
    quando: str | None = None  # expressão original
    prazo: str = ""  # AAAA-MM-DD calculado
    hora: str = ""  # HH:MM
    combinado: bool = False  # prazo foi dito na reunião (senão, padrão de 2 dias úteis)
    agendamento: int | None = None

    def descrever(self) -> str:
        quem = "" if self.responsavel == "assessor" else "cobrar do cliente: "
        prazo = datetime.strptime(self.prazo, "%Y-%m-%d").strftime("%d/%m") if self.prazo else "sem data"
        extra = f" {self.hora}" if self.hora else ""
        aviso = "" if self.combinado else " (prazo sugerido)"
        return f"{quem}{self.texto} — {prazo}{extra}{aviso}" + (f" · lembrete #{self.agendamento}" if self.agendamento else "")


@dataclass
class Reuniao:
    id: str
    cliente: str
    data: str
    resumo: list[str] = field(default_factory=list)
    decisoes: list[str] = field(default_factory=list)
    tarefas: list[Tarefa] = field(default_factory=list)
    proximo_contato: str = ""
    proximo_contato_hora: str = ""
    ficha: list[dict[str, Any]] = field(default_factory=list)  # sugestões validadas
    pontos_de_atencao: list[str] = field(default_factory=list)
    perfil_sinais: list[str] = field(default_factory=list)
    compliance: list[str] = field(default_factory=list)
    origem: str = "ia"  # ia | regras
    avisos: list[str] = field(default_factory=list)
    transcricao: str = ""
    ficha_aplicada: bool = False

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Reuniao":
        return cls(**{**d, "tarefas": [Tarefa(**t) for t in d.get("tarefas", [])]})

    def markdown(self) -> str:
        quando = datetime.fromisoformat(self.data).strftime("%d/%m/%Y %H:%M")
        partes = [f"📝 Pós-reunião {self.cliente} — {quando}" + (" (leitura por regras, sem IA)" if self.origem == "regras" else "")]
        if self.resumo:
            partes.append("Resumo:\n" + "\n".join(f"• {r}" for r in self.resumo))
        if self.decisoes:
            partes.append("Decisões:\n" + "\n".join(f"• {d}" for d in self.decisoes))
        if self.tarefas:
            partes.append("Tarefas (viraram lembretes):\n" + "\n".join(f"☐ {t.descrever()}" for t in self.tarefas))
        if self.proximo_contato:
            partes.append(f"Próximo contato: {datetime.strptime(self.proximo_contato, '%Y-%m-%d').strftime('%d/%m/%Y')}"
                          + (f" às {self.proximo_contato_hora}" if self.proximo_contato_hora else "") + " (lembrete criado)")
        if self.pontos_de_atencao:
            partes.append("Atenção:\n" + "\n".join(f"• {p}" for p in self.pontos_de_atencao))
        if self.perfil_sinais:
            partes.append("Sinais de perfil/suitability:\n" + "\n".join(f"• {p}" for p in self.perfil_sinais))
        if self.ficha:
            partes.append("Para a ficha (confirme antes de aplicar):\n"
                          + "\n".join(f"• {s['campo']} = {s['valor']}" for s in self.ficha))
        if self.compliance:
            partes.append("Compliance (o que foi dito na reunião):\n" + "\n".join(self.compliance))
        partes += [f"⚠️ {a}" for a in self.avisos]
        return "\n\n".join(partes)


def pasta(cliente: str) -> Path:
    p = pasta_dados() / "reunioes" / codigo(cliente)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- leitura
def _pelo_cerebro(cliente: str, texto: str, hoje: date, **extras: Any) -> dict[str, Any]:
    r = cerebro.perguntar(PEDIDO.format(hoje=hoje.strftime("%d/%m/%Y"), dia_semana=DIAS_PT[hoje.weekday()], cliente=cliente,
                                        texto=texto[:20000], campos=", ".join(CAMPOS_FICHA)),
                          sistema=SISTEMA, temperatura=0, max_tokens=4000, response_format={"type": "json_object"}, **extras)
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", r.texto.strip())
    return json.loads(bruto[bruto.find("{"):bruto.rfind("}") + 1])


_VERBOS = r"(vou|vamos|preciso|precisa|ficou de|ficamos de|tenho que|tem que|combinamos de|combinei de|lembrar de|ele vai|ela vai|vai me)"
_PRAZO = (r"(amanh[ãa]|depois de amanh[ãa]|hoje|(?:na |nesta |próxima |proxima )?(?:segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)"
          r"(?:-feira)?(?: que vem| da semana que vem)?|semana que vem|próxima semana|dia \d{1,2}|\d{1,2}/\d{1,2}|"
          r"daqui a \w+ (?:dias?|semanas?)|em \w+ dias(?: úteis)?|fim do mês|mês que vem)(?:\s*(?:às|as)\s*\d{1,2}\s*(?:h|:)\s*\d{0,2})?")


def _por_regras(texto: str) -> dict[str, Any]:
    """Plano B sem IA: frases com intenção de ação viram tarefas; o resto vira resumo."""
    frases = [f.strip() for f in re.split(r"(?<=[.!?;])\s+|\n+", texto) if len(f.strip()) > 3]
    tarefas, resumo = [], []
    for f in frases:
        if re.search(_VERBOS, f, re.I):
            m = re.search(_PRAZO, f, re.I)
            cliente_faz = re.search(r"\b(ele|ela|o cliente|a cliente|eles) (vai|vão|ficou de|precisa)", f, re.I)
            limpa = re.sub(rf"^.*?\b{_VERBOS}\s+", "", f, flags=re.I).rstrip(".!;")
            tarefas.append({"texto": limpa[:1].upper() + limpa[1:], "responsavel": "cliente" if cliente_faz else "assessor",
                            "quando": m.group(0) if m else None})
        elif len(resumo) < 6:
            resumo.append(f)
    return {"resumo": resumo, "decisoes": [], "tarefas": tarefas, "proximo_contato": None, "ficha": [],
            "pontos_de_atencao": [], "perfil_sinais": []}


def _lista(v: Any) -> list[str]:
    return [str(x).strip() for x in (v or []) if str(x).strip()] if isinstance(v, list) else ([str(v)] if v else [])


def _validar_ficha(itens: Any) -> list[dict[str, Any]]:
    saida = []
    for s in itens or []:
        campo = str((s or {}).get("campo", "")).strip()
        if campo not in CAMPOS_FICHA:
            continue
        bruto = str(s.get("valor", "")).strip()
        try:
            if CAMPOS_FICHA[campo] is str:
                from quiron.servicos.planejamento import ficha as fichas

                valor: Any = _sem_acento(bruto).replace(" ", "_") if campo != "uf" else bruto.upper()
                aceitos = {"perfil": fichas.PERFIS, "estado_civil": fichas.ESTADOS_CIVIS, "ocupacao": fichas.OCUPACOES,
                           "uf": fichas.UFS}[campo]
                valor = OCUPACAO_SINONIMOS.get(valor, valor) if campo == "ocupacao" else valor
                if valor not in aceitos:
                    continue
            else:
                from quiron.servicos.carteira.leitura import numero

                n = numero(bruto)
                if n is None:
                    continue
                valor = CAMPOS_FICHA[campo](n)
        except (ValueError, TypeError):
            continue
        if valor in ("", None):
            continue
        saida.append({"campo": campo, "valor": valor, "trecho": str(s.get("trecho", ""))[:200]})
    return saida


# ---------------------------------------------------------------- processar
def processar(cliente: str, texto: str, agora: datetime | None = None, usar_cerebro: bool = True,
              criar_lembretes: bool = True, **extras: Any) -> Reuniao:
    cod = codigo(cliente)
    texto = (texto or "").strip()
    if len(texto) < 15:
        raise ValueError("conte um pouco mais sobre a reunião (o que foi falado, decidido e combinado)")
    from quiron.runtime.agendador import BRT

    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    hoje = agora.date()
    seguro, ocultos = mascarar_identificadores(texto)
    bruto: dict[str, Any] | None = None
    origem = "ia"
    avisos = []
    if usar_cerebro:
        try:
            bruto = _pelo_cerebro(cod, seguro, hoje, **extras)
        except (cerebro.CerebroIndisponivel, ValueError, json.JSONDecodeError) as e:
            logging.warning("pós-reunião pelo cérebro falhou (%s); usando regras", type(e).__name__)
    if not bruto:
        bruto, origem = _por_regras(seguro), "regras"
        avisos.append("Sem IA no momento: leitura por regras simples — confira tarefas e prazos.")
    if ocultos:
        avisos.append(f"{ocultos} dado(s) pessoal(is) (CPF/telefone/e-mail/conta) foram ocultados antes da leitura.")

    tarefas = []
    for t in bruto.get("tarefas") or []:
        if not isinstance(t, dict) or not str(t.get("texto", "")).strip():
            continue
        quando = t.get("quando") or None
        d = datas.interpretar(quando, hoje)
        h = datas.hora(quando)
        combinado = d is not None
        if d is None:  # sem prazo dito (ou já passou): sugere 2 dias úteis
            d = datas.somar_dias_uteis(hoje, 2)
        tarefas.append(Tarefa(str(t["texto"]).strip()[:200], "cliente" if str(t.get("responsavel", "")).lower().startswith("cli") else "assessor",
                              str(quando) if quando else None, d.isoformat(), f"{h[0]:02d}:{h[1]:02d}" if h else "", combinado))
    prox = datas.interpretar(bruto.get("proximo_contato"), hoje)
    prox_h = datas.hora(bruto.get("proximo_contato"))

    r = Reuniao(id=agora.strftime("%Y%m%d-%H%M%S"), cliente=cod, data=agora.isoformat(timespec="seconds"),
                resumo=_lista(bruto.get("resumo"))[:8], decisoes=_lista(bruto.get("decisoes")), tarefas=tarefas,
                proximo_contato=prox.isoformat() if prox else "",
                proximo_contato_hora=f"{prox_h[0]:02d}:{prox_h[1]:02d}" if prox and prox_h else "", ficha=_validar_ficha(bruto.get("ficha")),
                pontos_de_atencao=_lista(bruto.get("pontos_de_atencao")), perfil_sinais=_lista(bruto.get("perfil_sinais")),
                compliance=[a.descrever() for a in compliance.conferir(texto, dados_pessoais=False)],
                origem=origem, avisos=avisos, transcricao=texto)
    if criar_lembretes:
        _agendar(r, agora)
    salvar(r)
    return r


def _agendar(r: Reuniao, agora: datetime) -> None:
    from quiron.runtime.agendador import BRT, Agendador

    ag = Agendador()
    for t in r.tarefas:
        h, m = map(int, t.hora.split(":")) if t.hora else HORA_PADRAO
        quando = datetime.combine(date.fromisoformat(t.prazo), time(h, m), tzinfo=BRT)
        if quando <= agora:  # "hoje" sem hora: daqui a 1 hora
            quando = agora.replace(second=0, microsecond=0) + timedelta(hours=1)
        prefixo = f"[{r.cliente}] " + ("Cobrar do cliente: " if t.responsavel == "cliente" else "")
        t.agendamento = ag.criar(prefixo + t.texto, "lembrete", "uma vez", quando, agora=agora).id
    if r.proximo_contato:
        h, m = map(int, r.proximo_contato_hora.split(":")) if r.proximo_contato_hora else HORA_PADRAO
        quando = datetime.combine(date.fromisoformat(r.proximo_contato), time(h, m), tzinfo=BRT)
        if quando > agora:
            ag.criar(f"[{r.cliente}] Próximo contato combinado na reunião de {agora:%d/%m}", "lembrete", "uma vez", quando, agora=agora)


def salvar(r: Reuniao) -> Path:
    p = pasta(r.cliente)
    (p / f"{r.id}.json").write_text(json.dumps(r.como_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    (p / f"{r.id}.md").write_text(r.markdown() + "\n\n---\nAnotação original:\n" + r.transcricao + "\n", encoding="utf-8")
    return p / f"{r.id}.json"


def carregar(cliente: str, ident: str) -> Reuniao:
    arq = pasta(cliente) / f"{ident}.json"
    if not re.fullmatch(r"\d{8}-\d{6}", ident) or not arq.exists():
        raise ValueError(f"reunião {ident} de {codigo(cliente)} não encontrada")
    return Reuniao.de_dict(json.loads(arq.read_text(encoding="utf-8")))


def listar(cliente: str, limite: int = 10) -> list[Reuniao]:
    arqs = sorted(pasta(cliente).glob("*.json"), reverse=True)[:limite]
    return [Reuniao.de_dict(json.loads(a.read_text(encoding="utf-8"))) for a in arqs]


def aplicar_na_ficha(cliente: str, ident: str) -> str:
    """Aplica as sugestões da reunião na ficha (só os campos simples validados) e guarda a observação."""
    from quiron.servicos.planejamento import ficha as fichas

    r = carregar(cliente, ident)
    if r.ficha_aplicada:
        return "Essas sugestões já foram aplicadas."
    if not r.ficha:
        return "Essa reunião não trouxe dados para a ficha."
    dados: dict[str, Any] = {"cliente": r.cliente, **{s["campo"]: s["valor"] for s in r.ficha}}
    obs = ""
    if fichas.existe(r.cliente):
        obs = fichas.carregar(r.cliente).observacoes
    nota = f"Reunião {datetime.fromisoformat(r.data):%d/%m/%Y}: " + "; ".join(r.decisoes or r.resumo[:2])
    dados["observacoes"] = (obs + "\n" + nota).strip()[-2000:]
    try:
        f = fichas.salvar(dados)
    except (ValueError, TypeError) as e:
        return f"Não apliquei: {e}"
    r.ficha_aplicada = True
    salvar(r)
    return "✅ Ficha atualizada: " + ", ".join(f"{s['campo']} = {s['valor']}" for s in r.ficha) + f"\n\n{fichas.descrever(f)}"
