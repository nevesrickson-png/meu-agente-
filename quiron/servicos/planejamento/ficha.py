"""Ficha do cliente para planejamento (Fase 9): tudo o que o plano precisa, identificado só por CLI-XXX.

Guardada em `dados/fichas/CLI-XXX.json` (fora do git); cada alteração guarda a versão anterior em
`dados/fichas/historico/`. Nunca nome, CPF, endereço ou telefone — só o código e os números do planejamento.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from quiron.nucleo.config import pasta_dados

RE_CLIENTE = re.compile(r"CLI-[A-Z0-9]{1,12}")
OCUPACOES = ("clt", "servidor", "autonomo", "profissional_liberal", "empresario", "aposentado")
ESTADOS_CIVIS = ("solteiro", "casado", "uniao_estavel", "divorciado", "viuvo")
REGIMES = ("comunhao_parcial", "comunhao_universal", "separacao_total", "separacao_obrigatoria", "participacao_final")
TIPOS_BEM = ("residencia", "imovel", "investimento", "previdencia_pgbl", "previdencia_vgbl", "empresa", "veiculo", "outro")
PERFIS = ("conservador", "moderado", "arrojado")
UFS = ("AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ",
       "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO")


class FichaInvalida(ValueError):
    pass


def codigo(cliente: str) -> str:
    c = (cliente or "").strip().upper()
    if not RE_CLIENTE.fullmatch(c):
        raise FichaInvalida(f"cliente precisa ser um código CLI-XXX (recebi “{cliente}”) — nunca o nome")
    return c


@dataclass
class Dependente:
    relacao: str = "filho"  # filho | filha | pai | mae | outro
    idade: int = 0


@dataclass
class Bem:
    nome: str
    tipo: str = "investimento"  # TIPOS_BEM
    valor: float = 0.0
    liquido: bool | None = None  # resgatável em até ~30 dias (padrão pelo tipo)
    particular: bool = False  # bem particular (fora da meação: herdado/doado ou de antes do casamento em comunhão parcial)

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS_BEM:
            self.tipo = "outro"
        if self.liquido is None:
            self.liquido = self.tipo == "investimento"


@dataclass
class Divida:
    nome: str
    saldo: float = 0.0
    parcela_mensal: float = 0.0
    taxa_am: float | None = None  # % ao mês
    prazo_meses: int | None = None


@dataclass
class Seguro:
    tipo: str = "vida"  # vida | invalidez | doencas_graves | saude | outro
    cobertura: float = 0.0
    premio_mensal: float = 0.0


@dataclass
class Objetivo:
    nome: str
    valor: float = 0.0  # R$ de hoje
    prazo_anos: float = 1.0
    prioridade: int = 2  # 1 essencial · 2 importante · 3 desejável
    ja_acumulado: float = 0.0


@dataclass
class Empresa:
    faturamento_anual: float = 0.0
    despesas_anuais: float = 0.0  # custos operacionais sem pró-labore e sem impostos
    folha_anual: float = 0.0  # salários + encargos de funcionários (entra no fator R)
    atividade: str = "servicos"  # servicos (intelectual) — outras atividades ficam para depois
    iss: float | None = None  # alíquota do município (padrão em regras_mercado.yaml)
    regime_atual: str = ""  # pf | simples | presumido


@dataclass
class Ficha:
    cliente: str
    idade: int = 0
    uf: str = ""
    estado_civil: str = ""
    regime_bens: str = ""
    idade_conjuge: int | None = None
    dependentes: list[Dependente] = field(default_factory=list)
    ocupacao: str = ""
    renda_mensal_bruta: float = 0.0  # do titular (salário, honorários; empresário: retiradas totais pró-labore + lucros)
    pro_labore_mensal: float = 0.0  # empresário: parte das retiradas que é pró-labore (tributável na PF)
    renda_conjuge_mensal: float = 0.0
    outras_rendas_mensais: float = 0.0  # aluguéis etc. (não incluir rendimento de investimentos)
    decimo_terceiro: bool | None = None  # padrão: sim para CLT/servidor
    despesas_mensais: float = 0.0  # da família
    contribui_inss: bool = True
    inss_beneficio_mensal: float = 0.0  # estimativa do benefício (R$ de hoje) — Meu INSS
    idade_inss: int | None = None  # quando o benefício começa (padrão: idade da aposentadoria)
    patrimonio: list[Bem] = field(default_factory=list)
    dividas: list[Divida] = field(default_factory=list)
    seguros: list[Seguro] = field(default_factory=list)
    aporte_mensal: float = 0.0  # quanto investe hoje por mês
    aporte_pgbl_anual: float = 0.0
    gastos_saude_anual: float = 0.0  # dedutíveis no IR
    gastos_educacao_anual: float = 0.0
    objetivos: list[Objetivo] = field(default_factory=list)
    idade_aposentadoria: int | None = None
    renda_desejada_aposentadoria: float = 0.0  # R$ de hoje por mês
    perfil: str = ""
    carteira_id: str = ""
    empresa: Empresa | None = None
    observacoes: str = ""
    atualizado_em: str = ""

    # ------------------------------------------------------------ derivados
    @property
    def patrimonio_total(self) -> float:
        return sum(b.valor for b in self.patrimonio)

    @property
    def investimentos(self) -> float:
        """Patrimônio financeiro (investimentos + previdência): o que trabalha para os objetivos."""
        return sum(b.valor for b in self.patrimonio if b.tipo in {"investimento", "previdencia_pgbl", "previdencia_vgbl"})

    @property
    def liquido(self) -> float:
        return sum(b.valor for b in self.patrimonio if b.liquido)

    @property
    def dividas_total(self) -> float:
        return sum(d.saldo for d in self.dividas)

    @property
    def filhos(self) -> list[Dependente]:
        return [d for d in self.dependentes if d.relacao.lower().startswith("filh")]

    @property
    def casado(self) -> bool:
        return self.estado_civil in {"casado", "uniao_estavel"}

    @property
    def tem_13(self) -> bool:
        return self.decimo_terceiro if self.decimo_terceiro is not None else self.ocupacao in {"clt", "servidor"}

    # ------------------------------------------------------------ dados
    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Ficha":
        d = {k: v for k, v in dict(d).items() if k in {f.name for f in fields(cls)}}
        listas = {"dependentes": Dependente, "patrimonio": Bem, "dividas": Divida, "seguros": Seguro, "objetivos": Objetivo}
        for chave, classe in listas.items():
            itens = []
            for item in d.get(chave) or []:
                if isinstance(item, dict):
                    itens.append(classe(**{k: v for k, v in item.items() if k in {f.name for f in fields(classe)}}))
            d[chave] = itens
        if isinstance(d.get("empresa"), dict):
            d["empresa"] = Empresa(**{k: v for k, v in d["empresa"].items() if k in {f.name for f in fields(Empresa)}})
        d["cliente"] = codigo(d.get("cliente", ""))
        f = cls(**d)
        f.uf = (f.uf or "").upper().strip()
        for nome in ("estado_civil", "regime_bens", "ocupacao", "perfil"):
            setattr(f, nome, str(getattr(f, nome) or "").lower().strip().replace(" ", "_").replace("ã", "a").replace("ç", "c"))
        return f

    def validar(self) -> list[str]:
        """Pendências: o que falta ou está incoerente (o plano roda, mas avisa)."""
        p = []
        if not 18 <= (self.idade or 0) <= 100:
            p.append("idade do titular")
        if self.uf not in UFS:
            p.append("estado (UF) — define o ITCMD")
        if self.estado_civil not in ESTADOS_CIVIS:
            p.append("estado civil")
        if self.casado and self.regime_bens not in REGIMES:
            p.append("regime de bens (casado/união estável)")
        if self.ocupacao not in OCUPACOES:
            p.append(f"ocupação ({', '.join(OCUPACOES)})")
        if self.renda_mensal_bruta <= 0 and self.ocupacao != "aposentado":
            p.append("renda mensal bruta")
        if self.despesas_mensais <= 0:
            p.append("despesas mensais da família")
        if not self.patrimonio:
            p.append("patrimônio (lista de bens)")
        if not self.idade_aposentadoria and self.ocupacao != "aposentado":
            p.append("idade desejada para aposentadoria")
        if self.renda_desejada_aposentadoria <= 0:
            p.append("renda desejada na aposentadoria (R$ de hoje)")
        if self.perfil not in PERFIS:
            p.append("perfil de investidor")
        if self.contribui_inss and self.ocupacao != "aposentado" and not self.inss_beneficio_mensal:
            p.append("estimativa do benefício do INSS (Meu INSS) — sem ela o plano considera zero")
        if self.ocupacao == "empresario" and not self.empresa:
            p.append("dados da empresa (faturamento, despesas, folha) para o módulo PF × PJ")
        return p


# ---------------------------------------------------------------- armazenamento
def pasta() -> Path:
    p = pasta_dados() / "fichas"
    (p / "historico").mkdir(parents=True, exist_ok=True)
    return p


def existe(cliente: str) -> bool:
    return (pasta() / f"{codigo(cliente)}.json").exists()


def carregar(cliente: str) -> Ficha:
    arq = pasta() / f"{codigo(cliente)}.json"
    if not arq.exists():
        raise FichaInvalida(f"não existe ficha de {codigo(cliente)} — crie com salvar_ficha")
    return Ficha.de_dict(json.loads(arq.read_text(encoding="utf-8")))


def salvar(dados: dict[str, Any], substituir: bool = False) -> Ficha:
    """Cria ou atualiza (mescla campo a campo; listas enviadas substituem as antigas). Guarda a versão anterior."""
    cod = codigo(str(dados.get("cliente", "")))
    arq = pasta() / f"{cod}.json"
    atual: dict[str, Any] = {}
    if arq.exists():
        atual = json.loads(arq.read_text(encoding="utf-8"))
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (pasta() / "historico" / f"{cod}-{carimbo}.json").write_text(json.dumps(atual, ensure_ascii=False), encoding="utf-8")
    base = {} if substituir else atual
    if isinstance(base.get("empresa"), dict) and isinstance(dados.get("empresa"), dict):
        dados = {**dados, "empresa": {**base["empresa"], **dados["empresa"]}}
    novo = {**base, **{k: v for k, v in dados.items() if v is not None}, "cliente": cod,
            "atualizado_em": datetime.now().isoformat(timespec="seconds")}
    f = Ficha.de_dict(novo)  # valida tipos antes de gravar
    arq.write_text(json.dumps(f.como_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return f


def listar() -> list[Ficha]:
    saida = []
    for arq in sorted(pasta().glob("CLI-*.json")):
        try:
            saida.append(Ficha.de_dict(json.loads(arq.read_text(encoding="utf-8"))))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return saida


def campos() -> str:
    """Guia dos campos (para o agente montar a ficha conversando)."""
    return (
        "Ficha de planejamento (cliente só como CLI-XXX):\n"
        "- idade, uf (SP, RJ…), estado_civil (" + ", ".join(ESTADOS_CIVIS) + "), regime_bens (" + ", ".join(REGIMES) + "), "
        "idade_conjuge\n"
        "- dependentes: [{relacao: filho|filha|pai|mae|outro, idade}]\n"
        "- ocupacao (" + ", ".join(OCUPACOES) + "), renda_mensal_bruta (empresário: retiradas totais), "
        "pro_labore_mensal (empresário), renda_conjuge_mensal, outras_rendas_mensais (aluguéis; sem rendimento de "
        "investimentos), decimo_terceiro (padrão: sim p/ CLT e servidor), despesas_mensais (da família, SEM as parcelas "
        "de dívidas — elas vão em dividas)\n"
        "- contribui_inss, inss_beneficio_mensal (estimativa do Meu INSS, R$ de hoje), idade_inss\n"
        "- patrimonio: [{nome, tipo (" + ", ".join(TIPOS_BEM) + "), valor, liquido, particular}]\n"
        "- dividas: [{nome, saldo, parcela_mensal, taxa_am, prazo_meses}] · seguros: [{tipo: vida|invalidez|"
        "doencas_graves|saude, cobertura, premio_mensal}]\n"
        "- aporte_mensal, aporte_pgbl_anual, gastos_saude_anual, gastos_educacao_anual\n"
        "- objetivos: [{nome, valor (R$ de hoje), prazo_anos, prioridade 1-3, ja_acumulado}]\n"
        "- idade_aposentadoria, renda_desejada_aposentadoria (R$ de hoje/mês), perfil (" + ", ".join(PERFIS) + "), "
        "carteira_id (CART-… da Fase 8)\n"
        "- empresa (empresário/liberal): {faturamento_anual, despesas_anuais, folha_anual, iss, regime_atual: pf|simples|presumido}\n"
        "- observacoes (texto livre, sem dados pessoais)"
    )


def descrever(f: Ficha) -> str:
    from quiron.servicos.analise.relatorio import brl

    linhas = [f"Ficha {f.cliente} (atualizada em {f.atualizado_em[:16].replace('T', ' ')})",
              f"- {f.idade} anos · {f.uf or '?'} · {f.estado_civil or '?'}"
              + (f" ({f.regime_bens})" if f.casado else "") + f" · {len(f.filhos)} filho(s) · {f.ocupacao or '?'}",
              f"- Renda bruta {brl(f.renda_mensal_bruta)}/mês"
              + (f" + cônjuge {brl(f.renda_conjuge_mensal)}" if f.renda_conjuge_mensal else "")
              + (f" + outras {brl(f.outras_rendas_mensais)}" if f.outras_rendas_mensais else "")
              + f" · despesas {brl(f.despesas_mensais)}/mês · aporta {brl(f.aporte_mensal)}/mês",
              f"- Patrimônio {brl(f.patrimonio_total)} (financeiro {brl(f.investimentos)}) · dívidas {brl(f.dividas_total)}",
              f"- Aposentadoria: {f.idade_aposentadoria or '?'} anos com {brl(f.renda_desejada_aposentadoria)}/mês · "
              f"INSS {brl(f.inss_beneficio_mensal)}/mês · perfil {f.perfil or '?'}"]
    if f.objetivos:
        linhas.append("- Objetivos: " + "; ".join(f"{o.nome} {brl(o.valor)} em {o.prazo_anos:g} anos" for o in f.objetivos))
    pend = f.validar()
    if pend:
        linhas.append("⚠️ Falta: " + "; ".join(pend))
    return "\n".join(linhas)
