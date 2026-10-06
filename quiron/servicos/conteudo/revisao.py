"""Revisão automática de todo conteúdo antes de chegar ao Rickson:

1. Compliance (mesmas regras da assessoria: promessa, "sem risco", certezas, rentabilidade passada sem ressalva, FGC,
   pressão, dados pessoais) — alerta grave pede reescrita.
2. Números: todo número com % ou R$ (ou decimal) precisa aparecer nos insumos; o que não aparece é sinalizado.
3. Créditos: só as fontes realmente citadas com [n] (marcas saem do texto final).
4. Disclaimer: padrão + "não é relatório de análise" se citar empresa/ticker + aviso de uso de IA."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from quiron.nucleo.config import ler_yaml
from quiron.servicos.assessoria import compliance
from quiron.servicos.conteudo.insumos import Insumo

RE_MARCA = re.compile(r"\s?\[(\d+(?:\s*,\s*\d+)*)\]")
RE_NUMERO = re.compile(r"(R\$\s*)?([-−]\s?)?(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+|\d+\.\d{1,2}(?!\d)|\d+)\s*(%|p\.p\.|pontos? percentuais)?")
RE_DATA = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
RE_TICKER = re.compile(r"\b[A-Za-z]{4}(?:3|4|5|6|11|3[1-5])\b")
EMPRESAS = ("Petrobras", "Vale S.A.", "Itaú", "Bradesco", "WEG", "Ambev", "Banco do Brasil", "Magazine Luiza", "Nubank")


def config() -> dict:
    return ler_yaml("conteudo")


def _valor(txt: str) -> float:
    if re.fullmatch(r"\d+\.\d{1,2}", txt):  # ponto decimal ("10.5%")
        return float(txt)
    return float(txt.replace(".", "").replace(",", "."))


def _numeros(texto: str) -> list[tuple[str, float, str, bool]]:
    """(bruto, valor com sinal, unidade, tem_decimal) — datas ficam de fora (o dia/mês/ano não é dado)."""
    saida = []
    for m in RE_NUMERO.finditer(RE_DATA.sub(" ", texto)):
        rs, menos, num, pct = m.group(1), m.group(2), m.group(3), m.group(4)
        unidade = "R$" if rs else ("%" if pct == "%" else ("pp" if pct else ""))
        v = _valor(num) * (-1 if menos else 1)
        saida.append((m.group(0).strip(), v, unidade, "," in num or bool(re.fullmatch(r"\d+\.\d{1,2}", num))))
    return saida


def numeros_do_texto(texto: str) -> list[tuple[str, float]]:
    """Números que precisam de fonte: com %, p.p., R$ ou com casas decimais."""
    return [(bruto, v) for bruto, v, un, dec in _numeros(texto) if un or dec]


def conferir_numeros(texto: str, insumos: list[Insumo]) -> list[str]:
    """Número do texto sem par nos insumos (mesmo valor, sinal e unidade; número sem unidade nos insumos vale para
    R$/decimal, mas não para % — senão o ano "2026" ou um prazo validariam um "2026%" inventado)."""
    base = {(round(v, 4), un) for i in insumos for _, v, un, _ in _numeros(i.texto)}
    soltos = {v for v, un in base if un == ""}
    fora = []
    for bruto, v, un, dec in _numeros(texto):
        if not (un or dec):
            continue
        v = round(v, 4)
        if (v, un) in base or (un == "pp" and (v, "%") in base) or (un in ("R$", "") and v in soltos):
            continue
        fora.append(bruto)
    return fora


def citados(texto: str, insumos: list[Insumo]) -> list[Insumo]:
    ids = {int(x) for m in RE_MARCA.finditer(texto) for x in m.group(1).split(",")}
    return [i for i in insumos if i.id in ids]


def creditos(usados: list[Insumo]) -> list[str]:
    vistos, linhas = set(), []
    for i in usados:
        linha = i.credito + (f" — {i.link}" if i.link else "")
        if linha not in vistos:
            vistos.add(linha)
            linhas.append(linha)
    return linhas


def disclaimer(texto: str) -> str:
    d = config()["disclaimer"]
    partes = [d["padrao"]]
    if RE_TICKER.search(texto) or _cita_empresa(texto):
        partes.append(d["acoes"])
    partes.append(d["ia"])
    return " ".join(p.strip() for p in partes)


def _cita_empresa(texto: str) -> bool:
    try:  # mesma lista de empresas das notícias (inicial maiúscula; exceções como "Vale a pena")
        from quiron.servicos.noticias.classificacao import ativos
        if ativos(texto):
            return True
    except Exception:  # noqa: BLE001 — sem a lista das notícias, fica a curta
        pass
    return any(e in texto for e in EMPRESAS)


@dataclass
class Revisado:
    texto: str  # sem as marcas [n]
    creditos: list[str] = field(default_factory=list)
    disclaimer: str = ""
    alertas: list[str] = field(default_factory=list)  # compliance
    graves: bool = False
    numeros_sem_fonte: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)  # notas internas (ex.: regra ainda não conferida)

    def final(self, titulo: str = "") -> str:
        cab = "RASCUNHO — revise antes de publicar"
        partes = [cab] + ([f"# {titulo}"] if titulo else []) + [self.texto.strip(), "---", f"⚠️ {self.disclaimer}"]
        if self.creditos:
            partes.append("Fontes: " + " · ".join(self.creditos))
        assinatura = config().get("assinatura")
        if assinatura:
            partes.append(assinatura)
        return "\n\n".join(partes)

    def notas(self) -> str:
        linhas = []
        if self.alertas:
            linhas += ["Compliance:"] + self.alertas
        if self.numeros_sem_fonte:
            linhas.append("Números sem fonte nos insumos (confira ou tire): " + ", ".join(self.numeros_sem_fonte))
        linhas += [f"⚠️ {a}" for a in self.avisos]
        if not (self.alertas or self.numeros_sem_fonte):
            linhas.insert(0, "✅ Compliance e números conferidos com as fontes.")
        return "\n".join(linhas)


def formatar(texto: str) -> str:
    """Quebra de linha antes de cada slide/post numerado (o modelo às vezes manda tudo numa linha só)."""
    texto = re.sub(r"\s*(\[?(?:Slide|Post|Bloco|Cena)\s+\d+\]?\s*[:\-—]?)", r"\n\n\1", texto)
    texto = re.sub(r"(?<=[.!?])\s+(\d{1,2}/\d{0,2}\s)", r"\n\n\1", texto)  # fios "1/8 …"
    return texto.strip()


def revisar(texto_com_marcas: str, insumos: list[Insumo]) -> Revisado:
    usados = citados(texto_com_marcas, insumos)
    limpo = formatar(RE_MARCA.sub("", texto_com_marcas))
    alertas = compliance.conferir(limpo)
    return Revisado(limpo, creditos(usados), disclaimer(limpo), [a.descrever() for a in alertas],
                    any(a.gravidade == "grave" for a in alertas), conferir_numeros(limpo, insumos),
                    sorted({i.aviso for i in usados if i.aviso}))
