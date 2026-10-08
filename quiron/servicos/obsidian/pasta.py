"""A pasta do Cérebro e as regras de escrita.

Quem escreve onde (decisão do Rickson, 07/10/2026 — "sugere, você aprova"):
- `Quíron/`         → o Quíron escreve livremente (diário, memória, estudo, mercado, melhorias).
- `Minhas notas/`   → é do Rickson. O Quíron só CRIA arquivos novos em `Minhas notas/Entrada/` (o que ele mandou anotar
                      pelo /nota) e nunca sobrescreve nem edita o texto de uma nota existente.
- `Modelos/`        → modelos de nota (criados uma vez; depois são do Rickson).
A configuração do Obsidian (`.obsidian/`) só é criada se ainda não existir — o Obsidian é dono dela depois.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from quiron.nucleo.config import pasta_dados
from quiron.nucleo.trava import gravar_atomico

QUIRON = "Quíron"
MINHAS = "Minhas notas"
ENTRADA = f"{MINHAS}/Entrada"
MODELOS = "Modelos"
DIARIO = f"{QUIRON}/Diário"
MEMORIA = f"{QUIRON}/Memória"
SUBPASTAS = (ENTRADA, f"{MINHAS}/Anexos", DIARIO, MEMORIA, f"{QUIRON}/Estudo", f"{QUIRON}/Mercado", f"{QUIRON}/Melhorias",
             MODELOS)
ARQ_MEMORIA = f"{MEMORIA}/Memória do Quíron.md"


class EscritaRecusada(ValueError):
    """Tentativa de escrever fora do que o Quíron pode mexer."""


def pasta() -> Path:
    return Path(os.environ.get("QUIRON_CEREBRO") or pasta_dados() / "cerebro")


def nfc(texto: str) -> str:
    return unicodedata.normalize("NFC", texto)


def relativo(arq: Path) -> str:
    """Caminho da nota dentro do cofre, sempre com '/' (igual no Windows e no Linux)."""
    return nfc(arq.resolve().relative_to(pasta().resolve()).as_posix())


def caminho(rel: str) -> Path:
    """Caminho absoluto de uma nota; recusa qualquer coisa que saia do cofre (../, absoluto, unidade do Windows)."""
    rel = nfc((rel or "").replace("\\", "/").strip().lstrip("/"))
    if not rel or re.match(r"^[A-Za-z]:", rel) or any(p in ("..", "") for p in rel.split("/")):
        raise EscritaRecusada(f"caminho inválido: {rel!r}")
    alvo = (pasta() / rel).resolve()
    if pasta().resolve() not in alvo.parents:
        raise EscritaRecusada(f"caminho fora do Cérebro: {rel!r}")
    return alvo


_PROIBIDOS = re.compile(r'[<>:"/\\|?*#^\[\]\x00-\x1f]')  # Windows + caracteres que quebram links do Obsidian
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def nome_arquivo(titulo: str, limite: int = 80) -> str:
    """Título → nome de arquivo válido no Windows e no Obsidian (sem extensão)."""
    nome = re.sub(r"\s+", " ", _PROIBIDOS.sub(" ", nfc(titulo or ""))).strip().rstrip(". ")
    nome = nome[:limite].rstrip(". ") or "Nota"
    return f"{nome} (nota)" if nome.upper() in _RESERVADOS else nome


def gravar_quiron(rel: str, texto: str) -> Path:
    """Grava (cria ou substitui) uma nota da pasta `Quíron/`. Fora dela, recusa."""
    alvo = caminho(rel)
    if not relativo(alvo).startswith(QUIRON + "/"):
        raise EscritaRecusada("o Quíron só reescreve notas da pasta Quíron/")
    gravar_atomico(alvo, texto)
    return alvo


def criar_nova(rel_pasta: str, titulo: str, texto: str) -> Path:
    """Cria uma nota NOVA (nunca sobrescreve: acrescenta ' 2', ' 3'…). Usada para o /nota em Minhas notas/Entrada."""
    base = caminho(rel_pasta)
    rel_base = relativo(base) if base != pasta().resolve() else ""
    if not (rel_base == ENTRADA or rel_base.startswith(QUIRON + "/") or rel_base == QUIRON):
        raise EscritaRecusada("o Quíron só cria notas em Minhas notas/Entrada ou na pasta Quíron/")
    base.mkdir(parents=True, exist_ok=True)
    nome = nome_arquivo(titulo)
    for n in range(1, 500):
        alvo = base / (f"{nome}.md" if n == 1 else f"{nome} {n}.md")
        try:
            with alvo.open("x", encoding="utf-8") as f:  # "x" = falha se já existe (sem corrida entre processos)
                f.write(texto)
            return alvo
        except FileExistsError:
            continue
    raise EscritaRecusada("nomes demais iguais")


# ---------------------------------------------------------------- frontmatter (o mínimo do YAML que o Obsidian usa)
def ler_frontmatter(texto: str) -> tuple[dict[str, object], str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?", texto, re.S)
    if not m:
        return {}, texto
    dados: dict[str, object] = {}
    chave_lista = None
    for linha in m.group(1).splitlines():
        item = re.match(r"\s+-\s*(.+)", linha)
        if item and chave_lista:
            dados.setdefault(chave_lista, [])
            if isinstance(dados[chave_lista], list):
                dados[chave_lista].append(item.group(1).strip().strip("'\""))
            continue
        kv = re.match(r"([\wÀ-ÿ-]+):\s*(.*)", linha)
        if not kv:
            continue
        chave, valor = kv.group(1), kv.group(2).strip()
        chave_lista = chave if not valor else None
        if valor.startswith("[") and valor.endswith("]"):
            dados[chave] = [v.strip().strip("'\"") for v in valor[1:-1].split(",") if v.strip()]
        elif valor:
            dados[chave] = valor.strip("'\"")
    return dados, texto[m.end():]


def frontmatter(campos: dict[str, object]) -> str:
    linhas = ["---"]
    for k, v in campos.items():
        if isinstance(v, (list, tuple)):
            linhas.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        elif v not in (None, ""):
            linhas.append(f"{k}: {v}")
    return "\n".join(linhas + ["---", ""])


# ---------------------------------------------------------------- estrutura inicial
LEIA_ME = """# Cérebro do Quíron

Esta pasta é um **cofre do Obsidian**: abra o Obsidian → *Abrir pasta como cofre* → escolha esta pasta.

- **Minhas notas/** — é só sua. O Quíron lê tudo, mas nunca muda o seu texto. O que você manda anotar pelo Telegram
  (`/nota …`) chega em *Minhas notas/Entrada*.
- **Quíron/** — onde o Quíron escreve sozinho: *Diário* (uma nota por dia), *Memória* (o que ele sabe de você — pode
  corrigir ou apagar linhas ali que ele passa a usar a versão certa), *Estudo*, *Mercado* e *Melhorias*.
- **Modelos/** — modelos de nota (livro, conceito, tese, reflexão).

Clientes ficam de fora: use só o código CLI-XXX e nunca escreva nome, CPF, telefone ou e-mail de cliente aqui.
Quando você pergunta algo às suas notas, o trecho relevante vai para a IA gratuita (com telefone/CPF/e-mail mascarados).
"""

MODELOS_PADRAO = {
    "Livro.md": "---\ntipo: livro\nautor: \ntags: [livro]\n---\n# {{title}}\n\n## Ideia central\n\n## O que levo para a prática\n\n"
                "## Citações (com página)\n\n## Ligações\n- \n",
    "Conceito.md": "---\ntipo: conceito\ntags: [conceito]\n---\n# {{title}}\n\n## Definição em uma frase\n\n## Como funciona\n\n"
                   "## Exemplo com números\n\n## Erros comuns\n\n## Ligações\n- \n",
    "Tese.md": "---\ntipo: tese\nativo: \nhorizonte: \nconfiança: \ntags: [tese]\n---\n# {{title}}\n\n## A tese\n\n"
               "## Por que agora\n\n## O que a invalidaria\n\n## Como vou acompanhar\n",
    "Reflexão.md": "---\ntipo: reflexão\ndata: {{date}}\ntags: [reflexão]\n---\n# Reflexão — {{date}}\n\n"
                   "## O que aprendi\n\n## O que decidi\n\n## O que faria diferente\n",
}

OBSIDIAN = {  # só o essencial; o Obsidian completa o resto na primeira abertura
    "app.json": {"newFileLocation": "folder", "newFileFolderPath": MINHAS, "attachmentFolderPath": f"{MINHAS}/Anexos",
                 "alwaysUpdateLinks": True},
    "daily-notes.json": {"folder": DIARIO, "format": "YYYY-MM-DD"},
    "templates.json": {"folder": MODELOS},
}


def garantir() -> Path:
    """Cria a estrutura que faltar. Nunca sobrescreve nada que já exista."""
    raiz = pasta()
    for sub in SUBPASTAS:
        (raiz / sub).mkdir(parents=True, exist_ok=True)
    if not (raiz / "LEIA-ME.md").exists():
        gravar_atomico(raiz / "LEIA-ME.md", LEIA_ME)
    for nome, texto in MODELOS_PADRAO.items():
        if not (raiz / MODELOS / nome).exists():
            gravar_atomico(raiz / MODELOS / nome, texto)
    (raiz / ".obsidian").mkdir(exist_ok=True)
    for nome, conteudo in OBSIDIAN.items():
        if not (raiz / ".obsidian" / nome).exists():
            gravar_atomico(raiz / ".obsidian" / nome, json.dumps(conteudo, ensure_ascii=False, indent=2))
    return raiz


def link_obsidian(rel: str) -> str:
    """Endereço que abre a nota no Obsidian (o cofre precisa ter sido aberto uma vez)."""
    from urllib.parse import quote

    return f"obsidian://open?vault={quote(pasta().name)}&file={quote(rel.removesuffix('.md'))}"


def agora() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
