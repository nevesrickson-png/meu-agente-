"""Anonimizador: roda ANTES de qualquer envio de texto a um modelo de linguagem.

Troca dados identificáveis por marcadores ([CPF_1], [NOME_1], [EMAIL_1]...) e guarda o mapa
apenas em memória, para desfazer a troca na resposta do modelo. O mapa nunca é gravado em disco.

O que é detectado:
- e-mail, CPF, CNPJ, telefone brasileiro, RG, CEP;
- nomes cadastrados como protegidos (lista passada pelo Rickson, ex.: `segredos/nomes_protegidos.txt`);
- nomes depois de pistas como "cliente", "Sr.", "Sra.", "Dr.", "dona", "seu";
- nomes compostos que começam por um prenome brasileiro comum ("Maria Souza", "João Pedro Lima").

Códigos de cliente (CLI-XXX) já são anônimos e não são alterados.
A detecção de nomes é heurística: na dúvida, prefere anonimizar a mais.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- documentos e contatos

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_CPF_FORMATADO = re.compile(r"(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\d-])")
_CNPJ_FORMATADO = re.compile(r"(?<![\d.])\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?![\d-])")
_RG = re.compile(r"\bRG\s*(?:n[ºo°.]?\s*)?:?\s*[\dXx][\d.\-Xx]{4,14}\d?\b", re.IGNORECASE)
_CEP = re.compile(r"(?<![\d.])\d{5}-\d{3}(?![\d-])")
_DIGITOS_SOLTOS = re.compile(r"(?<![\d.,/-])\d{11}(?:\d{3})?(?![\d.,/-])")
_TELEFONE = re.compile(
    r"(?<![\w.,/])"
    r"(?:\+?55[\s.-]?)?"
    r"(?:\(\d{2}\)|\d{2})[\s.-]?"
    r"9?\d{4}[\s.-]?\d{4}"
    r"(?![\w,/]|\.\d)"
)


def _dv_valido(numeros: str, pesos: list[int]) -> bool:
    """Confere os 2 dígitos verificadores (módulo 11) de CPF/CNPJ.

    `pesos` são os do 2º dígito; o 1º usa os mesmos pesos sem o primeiro elemento.
    """
    corpo = [int(c) for c in numeros]
    for p in (pesos[1:], pesos):
        resto = sum(d * w for d, w in zip(corpo, p)) % 11
        if corpo[len(p)] != (0 if resto < 2 else 11 - resto):
            return False
    return True


def cpf_valido(texto: str) -> bool:
    n = re.sub(r"\D", "", texto)
    if len(n) != 11 or n == n[0] * 11:
        return False
    return _dv_valido(n, list(range(11, 1, -1)))


def cnpj_valido(texto: str) -> bool:
    n = re.sub(r"\D", "", texto)
    if len(n) != 14 or n == n[0] * 14:
        return False
    return _dv_valido(n, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])


# ---------------------------------------------------------------- nomes

_MAIUSCULA = "A-ZÁÀÂÃÉÊÍÓÔÕÚÇ"
_MINUSCULA = "a-záàâãéêíóôõúüç"
_PALAVRA_NOME = rf"[{_MAIUSCULA}][{_MINUSCULA}]+(?:-[{_MAIUSCULA}][{_MINUSCULA}]+)?"
_CONECTOR = r"(?:da|de|do|das|dos|e|d')"
# um ou mais nomes próprios, com conectores entre eles ("Ana Maria de Souza")
_SEQ_NOME = rf"{_PALAVRA_NOME}(?:\s+(?:{_CONECTOR}\s+)?{_PALAVRA_NOME})*"

_PISTAS = (
    r"cliente|clientes|cliente\s+novo|cliente\s+nova|prospect|lead|investidor|investidora|"
    r"sr\.?|sra\.?|srta\.?|dr\.?|dra\.?|senhor|senhora|dona|seu|esposa|esposo|marido|mulher|"
    r"filho|filha|sócio|sócia|herdeiro|herdeira|cônjuge|conjuge"
)
_NOME_APOS_PISTA = re.compile(rf"(?<![\w])(?:{_PISTAS})\s+(?:o\s+|a\s+)?(?P<nome>{_SEQ_NOME})", re.IGNORECASE)

# Prenomes comuns no Brasil: uma sequência de nomes próprios que começa por um deles é tratada como nome.
PRENOMES_COMUNS = frozenset(
    """
    ana maria antonia antônia adriana aline alice amanda andreia andréia angela ângela beatriz bianca bruna
    camila carla carolina catarina cecilia cecília clara claudia cláudia cristina daniela debora débora eduarda
    elaine eliane elisa fabiana fernanda flavia flávia francisca gabriela giovana heloisa heloísa isabel isabela
    isadora jaqueline jessica jéssica joana josefa juliana julia júlia larissa laura leticia letícia lívia livia
    lorena luana lucia lúcia luciana luiza luísa luisa manuela mariana marina marta mônica monica natalia natália
    patricia patrícia paula priscila rafaela raquel regina renata rita roberta rosa sandra sara silvia sílvia
    simone sofia sônia sonia suzana tatiana teresa tereza valentina vanessa vera vitoria vitória yasmin
    joao joão jose josé antonio antônio francisco carlos paulo pedro lucas luiz luis luís marcos gabriel rafael
    daniel marcelo bruno eduardo felipe rodrigo manoel manuel ricardo fernando fabio fábio jorge andre andré
    alexandre sergio sérgio roberto mateus matheus thiago tiago leonardo gustavo diego vinicius vinícius
    henrique guilherme samuel davi david miguel arthur artur heitor bernardo enzo igor caio otavio otávio
    renato rogerio rogério marcio márcio claudio cláudio julio júlio cesar césar raimundo sebastiao sebastião
    benedito geraldo luciano leandro edson wagner wellington anderson alan adriano alberto alfredo alvaro
    álvaro augusto benjamin breno cristiano danilo emerson erick evandro flavio flávio gilberto gilmar
    hugo jair jonas joaquim juliano leo léo lourenço mauricio maurício mauro milton murilo nelson nicolas
    osvaldo otto ronaldo rubens silvio sílvio valter walter victor vitor wilson
    """.split()
)

_SEQ_NOME_RE = re.compile(rf"(?<![\w])(?P<nome>{_SEQ_NOME})")


def _palavras(nome: str) -> list[str]:
    return [p for p in re.split(r"\s+", nome) if not re.fullmatch(_CONECTOR, p, re.IGNORECASE)]


def carregar_nomes_protegidos(caminho: Path) -> list[str]:
    """Um nome por linha; linhas vazias e iniciadas por # são ignoradas."""
    if not caminho.exists():
        return []
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in linhas if l.strip() and not l.strip().startswith("#")]


# ---------------------------------------------------------------- anonimizador


@dataclass
class Anonimizador:
    """Uma instância por conversa/pedido. Mesmo valor → mesmo marcador."""

    nomes_protegidos: list[str] = field(default_factory=list)
    _mapa: dict[str, str] = field(default_factory=dict, init=False, repr=False)  # marcador → original
    _reverso: dict[tuple[str, str], str] = field(default_factory=dict, init=False, repr=False)
    _contadores: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    # -- marcadores
    def _marcador(self, tipo: str, original: str) -> str:
        chave = (tipo, self._normalizar(tipo, original))
        if chave not in self._reverso:
            self._contadores[tipo] = self._contadores.get(tipo, 0) + 1
            marcador = f"[{tipo}_{self._contadores[tipo]}]"
            self._reverso[chave] = marcador
            self._mapa[marcador] = original
        return self._reverso[chave]

    @staticmethod
    def _normalizar(tipo: str, valor: str) -> str:
        if tipo in {"CPF", "CNPJ", "TELEFONE", "CEP", "RG"}:
            return re.sub(r"\D", "", valor)[-11:] if tipo == "TELEFONE" else re.sub(r"\W", "", valor).upper()
        return re.sub(r"\s+", " ", valor).strip().casefold()

    @property
    def mapa(self) -> dict[str, str]:
        """Cópia do mapa marcador → original (somente memória)."""
        return dict(self._mapa)

    # -- troca
    def anonimizar(self, texto: str) -> str:
        if not texto:
            return texto
        t = _EMAIL.sub(lambda m: self._marcador("EMAIL", m.group()), texto)
        t = _CNPJ_FORMATADO.sub(lambda m: self._marcador("CNPJ", m.group()), t)
        t = _CPF_FORMATADO.sub(lambda m: self._marcador("CPF", m.group()), t)
        t = _DIGITOS_SOLTOS.sub(self._documento_solto, t)
        t = _RG.sub(lambda m: self._marcador("RG", m.group()), t)
        t = _CEP.sub(lambda m: self._marcador("CEP", m.group()), t)
        t = _TELEFONE.sub(lambda m: self._marcador("TELEFONE", m.group()), t)
        t = self._anonimizar_nomes(t)
        return t

    def _documento_solto(self, m: re.Match[str]) -> str:
        v = m.group()
        if len(v) == 11 and cpf_valido(v):
            return self._marcador("CPF", v)
        if len(v) == 14 and cnpj_valido(v):
            return self._marcador("CNPJ", v)
        return v  # 11 dígitos sem DV de CPF: o filtro de telefone decide depois

    def _anonimizar_nomes(self, texto: str) -> str:
        # 1) nomes cadastrados (mais longos primeiro, sem diferenciar maiúsculas)
        for nome in sorted(self.nomes_protegidos, key=len, reverse=True):
            padrao = re.compile(rf"(?<![\w]){re.escape(nome)}(?![\w])", re.IGNORECASE)
            texto = padrao.sub(lambda m: self._marcador("NOME", m.group()), texto)

        # 2) nome depois de pista ("cliente Fulano", "Sra. Fulana")
        def _troca_pista(m: re.Match[str]) -> str:
            nome = m.group("nome")
            inicio = m.start("nome") - m.start()
            return m.group()[:inicio] + self._marcador("NOME", nome)

        texto = _NOME_APOS_PISTA.sub(_troca_pista, texto)

        # 3) sequência de nomes próprios que começa por prenome comum
        def _troca_prenome(m: re.Match[str]) -> str:
            nome = m.group("nome")
            partes = _palavras(nome)
            if partes and partes[0].casefold() in PRENOMES_COMUNS:
                return self._marcador("NOME", nome)
            return nome

        texto = _SEQ_NOME_RE.sub(_troca_prenome, texto)

        # 4) um nome detectado em qualquer ponto vale para o texto todo: troca as outras ocorrências
        #    (nome completo e cada parte dele, ex.: "Odete" sozinha depois de "Sra. Odete Pires")
        detectados = [v for k, v in self._mapa.items() if k.startswith("[NOME_")]
        partes = {p for n in detectados for p in _palavras(n) if len(p) >= 3}
        for alvo in sorted(set(detectados) | partes, key=len, reverse=True):
            padrao = re.compile(rf"(?<![\w\[]){re.escape(alvo)}(?![\w\]])", re.IGNORECASE)
            texto = padrao.sub(lambda m: self._marcador("NOME", m.group()), texto)
        return texto

    def desanonimizar(self, texto: str) -> str:
        """Devolve os valores originais no texto (ex.: resposta do modelo)."""
        if not texto or not self._mapa:
            return texto
        padrao = re.compile("|".join(re.escape(m) for m in sorted(self._mapa, key=len, reverse=True)))
        return padrao.sub(lambda m: self._mapa[m.group()], texto)


def anonimizar(texto: str, nomes_protegidos: list[str] | None = None) -> str:
    """Atalho para quando não é preciso desfazer a troca."""
    return Anonimizador(nomes_protegidos or []).anonimizar(texto)
