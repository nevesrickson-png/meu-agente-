"""Workspace do agente (ideia do OpenClaw): o "cérebro" do Quíron em arquivos Markdown que o Rickson pode ler e editar.

Modelos ficam em `agente/workspace/` (no Git). A cópia viva fica em `dados/workspace/` (fora do Git, entra no backup),
porque a memória e o diário guardam coisas pessoais.
- SOUL.md     → gerado de `agente/persona.md` (não se edita aqui)
- USUARIO.md  → quem é o Rickson
- MEMORIA.md  → espelho legível e editável da memória persistente (`dados/memoria.db`, ver memoria_longa.py)
- ROTINAS.md  → o que vigiar no batimento proativo
- diario/AAAA-MM-DD.md → registro do dia (resumos de conversa, avisos enviados)
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quiron.nucleo.config import PASTA_AGENTE, pasta_dados

BRT = ZoneInfo("America/Sao_Paulo")
ARQUIVOS = ("USUARIO.md", "MEMORIA.md", "ROTINAS.md")


@dataclass
class Workspace:
    raiz: Path

    @classmethod
    def padrao(cls) -> "Workspace":
        ws = cls(pasta_dados() / "workspace")
        ws.garantir()
        return ws

    def garantir(self) -> None:
        """Cria a cópia viva a partir dos modelos, sem nunca sobrescrever o que já existe."""
        (self.raiz / "diario").mkdir(parents=True, exist_ok=True)
        for nome in ARQUIVOS:
            if not (self.raiz / nome).exists():
                shutil.copy(PASTA_AGENTE / "workspace" / nome, self.raiz / nome)

    def ler(self, nome: str) -> str:
        if nome == "SOUL.md":
            return (PASTA_AGENTE / "persona.md").read_text(encoding="utf-8")
        caminho = self.raiz / nome
        return caminho.read_text(encoding="utf-8") if caminho.exists() else ""

    # ------------------------------------------------------------ memória de longo prazo (fonte única: memoria_longa)
    def _longa(self):
        from quiron.runtime.memoria_longa import MemoriaLonga

        return MemoriaLonga(arquivo_md=self.raiz / "MEMORIA.md")

    def fatos(self) -> list[str]:
        return [f.texto for f in self._longa().fatos()]

    def lembrar(self, fato: str) -> str:
        return self._longa().adicionar(fato, "geral", 4, "dito")[0]

    def esquecer(self, trecho: str) -> str:
        return self._longa().esquecer(trecho)

    # ------------------------------------------------------------ diário
    def anotar_diario(self, texto: str, quando: datetime | None = None) -> None:
        quando = quando or datetime.now(BRT)
        arq = self.raiz / "diario" / f"{quando:%Y-%m-%d}.md"
        novo = not arq.exists()
        with arq.open("a", encoding="utf-8") as f:
            if novo:
                f.write(f"# Diário do Quíron — {quando:%d/%m/%Y}\n\n")
            f.write(f"- {quando:%H:%M} {texto.strip()}\n")

    def diario(self, dia: datetime | None = None) -> str:
        dia = dia or datetime.now(BRT)
        arq = self.raiz / "diario" / f"{dia:%Y-%m-%d}.md"
        return arq.read_text(encoding="utf-8") if arq.exists() else ""


@dataclass
class Comando:
    nome: str
    descricao: str
    modelo: str  # texto do pedido; {args} é trocado pelo que vem depois do comando
    skill: str = ""  # skill carregada junto (poupa uma ida e volta ao modelo)
    padrao: str = "o mercado hoje"  # o que entra no {args} quando o comando vem sem nada

    def montar(self, args: str) -> str:
        return self.modelo.replace("{args}", args.strip() or self.padrao).strip()


def carregar_comandos(pasta: Path | None = None) -> dict[str, Comando]:
    """Comandos de barra em Markdown (ideia do Claude Code): agente/comandos/<nome>.md vira /<nome>."""
    pasta = pasta or PASTA_AGENTE / "comandos"
    saida = {}
    for arq in sorted(pasta.glob("*.md")):
        texto = arq.read_text(encoding="utf-8")
        descricao = skill = ""
        m = re.match(r"---\s*\n(.*?)\n---\s*\n", texto, re.S)
        if m:
            d = re.search(r"descricao:\s*(.+)", m.group(1))
            descricao = d.group(1).strip() if d else ""
            s = re.search(r"skill:\s*(.+)", m.group(1))
            skill = s.group(1).strip() if s else ""
            p = re.search(r"padrao:\s*(.+)", m.group(1))
            padrao = p.group(1).strip() if p else Comando.padrao
            texto = texto[m.end():]
        else:
            padrao = Comando.padrao
        saida[arq.stem] = Comando(arq.stem, descricao, texto.strip(), skill, padrao)
    return saida
