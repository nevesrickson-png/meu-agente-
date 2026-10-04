"""Áreas de conhecimento (campos + certificações): pastas do acervo e trilhas da Academia.

- Campos e certificações extras: `config/areas_conhecimento.yaml`; trilha de certificações: `config/trilha_certificacoes.yaml`.
- Áreas criadas pelo Rickson na tela do Acervo: `dados/areas_personalizadas.yaml` (fora do git: não somem nas atualizações).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from quiron.nucleo.config import PASTA_CONFIG, pasta_dados


@dataclass
class Area:
    id: str
    nome: str
    tipo: str  # "campo" | "certificacao"
    descricao: str = ""
    relacionadas: list[str] = field(default_factory=list)
    personalizada: bool = False

    @property
    def pasta(self) -> str:
        """Nome da pasta no acervo (minúsculas, sem acento)."""
        return self.id.lower()


def _arquivo_personalizadas() -> Path:
    return pasta_dados() / "areas_personalizadas.yaml"


def _ler(arq: Path) -> dict:
    return (yaml.safe_load(arq.read_text(encoding="utf-8")) or {}) if arq.exists() else {}


def listar() -> list[Area]:
    base = _ler(PASTA_CONFIG / "areas_conhecimento.yaml")
    trilha = _ler(PASTA_CONFIG / "trilha_certificacoes.yaml").get("trilha", [])
    areas: dict[str, Area] = {}
    for c in base.get("campos", []):
        areas[c["id"]] = Area(c["id"], c["nome"], "campo", c.get("descricao", ""), c.get("certificacoes", []))
    for c in trilha:
        areas.setdefault(c["id"], Area(c["id"], c["id"].replace("_", " "), "certificacao",
                                       f"{c.get('entidade', '')} — {c.get('motivo', '')}".strip(" —")))
    for c in base.get("certificacoes_extras", []):
        areas.setdefault(c["id"], Area(c["id"], c.get("nome", c["id"]), "certificacao", c.get("descricao", "")))
    for c in _ler(_arquivo_personalizadas()).get("areas", []):
        areas.setdefault(c["id"], Area(c["id"], c["nome"], c.get("tipo", "campo"), c.get("descricao", ""), personalizada=True))
    # campos ligados a cada certificação (caminho inverso)
    for a in areas.values():
        if a.tipo == "certificacao":
            a.relacionadas = [c.id for c in areas.values() if c.tipo == "campo" and a.id in c.relacionadas]
    return list(areas.values())


def obter(ident: str) -> Area | None:
    ident = (ident or "").strip()
    return next((a for a in listar() if a.id == ident.upper() or a.pasta == ident.lower()), None)


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


def reconhecer(texto: str) -> tuple[Area | None, str]:
    """Acha uma área no começo do texto ('economia juros reais', 'cfp 3', 'renda fixa duration').
    Devolve (área, resto do texto)."""
    alvo = _sem_acento(texto.strip())
    melhor: tuple[int, Area | None, str] = (0, None, texto)
    for a in listar():
        for nome in {a.id.lower().replace("_", " "), a.id.lower(), _sem_acento(a.nome)}:
            if alvo == nome or alvo.startswith(nome + " "):
                if len(nome) > melhor[0]:
                    melhor = (len(nome), a, texto.strip()[len(nome):].strip())
    return melhor[1], melhor[2]


def criar(nome: str, descricao: str = "", tipo: str = "campo") -> Area:
    """Cria uma área personalizada (fica em dados/, não no git)."""
    nome = " ".join(nome.split())
    if not nome or len(nome) > 60:
        raise ValueError("Nome da área: de 1 a 60 caracteres.")
    ident = re.sub(r"[^A-Z0-9]+", "_", _sem_acento(nome).upper()).strip("_")[:30]
    if not ident:
        raise ValueError("Nome da área precisa ter letras ou números.")
    if obter(ident):
        raise ValueError(f"Já existe a área {ident}.")
    arq = _arquivo_personalizadas()
    dados = _ler(arq)
    dados.setdefault("areas", []).append({"id": ident, "nome": nome, "tipo": tipo if tipo in {"campo", "certificacao"} else "campo",
                                          "descricao": descricao.strip()[:200]})
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return obter(ident)  # type: ignore[return-value]
