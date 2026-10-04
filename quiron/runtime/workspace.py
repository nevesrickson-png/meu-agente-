"""Workspace do agente (ideia do OpenClaw): o "cérebro" do Quíron em arquivos Markdown que o Rickson pode ler e editar.

Modelos ficam em `agente/workspace/` (no Git). A cópia viva fica em `dados/workspace/` (fora do Git, entra no backup),
porque a memória e o diário guardam coisas pessoais.
- SOUL.md     → gerado de `agente/persona.md` (não se edita aqui)
- USUARIO.md  → quem é o Rickson
- MEMORIA.md  → fatos duráveis aprendidos (ferramenta `lembrar`)
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

    # ------------------------------------------------------------ memória de longo prazo
    def fatos(self) -> list[str]:
        return [re.sub(r"\s*_\(desde [^)]*\)_\s*$", "", l[2:]).strip() for l in self.ler("MEMORIA.md").splitlines() if l.startswith("- ")]

    def lembrar(self, fato: str) -> str:
        fato = re.sub(r"\s+", " ", fato).strip().lstrip("- ")
        if not fato:
            return "Nada para lembrar."
        if any(fato.casefold() == f.casefold() for f in self.fatos()):
            return f"Já estava na memória: {fato}"
        hoje = datetime.now(BRT).strftime("%d/%m/%Y")
        with (self.raiz / "MEMORIA.md").open("a", encoding="utf-8") as f:
            f.write(f"- {fato} _(desde {hoje})_\n")
        return f"Guardado na memória: {fato}"

    def esquecer(self, trecho: str) -> str:
        texto = self.ler("MEMORIA.md")
        linhas = texto.splitlines()
        alvo = trecho.casefold().strip()
        restantes = [l for l in linhas if not (l.startswith("- ") and alvo and alvo in l.casefold())]
        removidas = len(linhas) - len(restantes)
        if not removidas:
            return f"Nada na memória com “{trecho}”."
        (self.raiz / "MEMORIA.md").write_text("\n".join(restantes) + "\n", encoding="utf-8")
        return f"Esquecido: {removidas} item(ns) com “{trecho}”."

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

    def montar(self, args: str) -> str:
        return self.modelo.replace("{args}", args.strip() or "o mercado hoje").strip()


def carregar_comandos(pasta: Path | None = None) -> dict[str, Comando]:
    """Comandos de barra em Markdown (ideia do Claude Code): agente/comandos/<nome>.md vira /<nome>."""
    pasta = pasta or PASTA_AGENTE / "comandos"
    saida = {}
    for arq in sorted(pasta.glob("*.md")):
        texto = arq.read_text(encoding="utf-8")
        descricao = ""
        m = re.match(r"---\s*\n(.*?)\n---\s*\n", texto, re.S)
        if m:
            d = re.search(r"descricao:\s*(.+)", m.group(1))
            descricao = d.group(1).strip() if d else ""
            texto = texto[m.end():]
        saida[arq.stem] = Comando(arq.stem, descricao, texto.strip())
    return saida
