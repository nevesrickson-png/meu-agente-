"""LGPD — `/esquecer CLI-XXX` apaga tudo o que o Quíron guardou sobre um cliente.

Apaga: ficha (e histórico), carteiras lidas, relatórios (tarefas da fila + arquivos, inclusive os que só citam o cliente
dentro da carteira), anotações de reunião, lembretes, tarefas, notas e metas da organização, teses/treinos/ideias,
trechos de conversa, linhas da memória e do diário, as CÓPIAS da memória (backups diários e "antes de restaurar"),
exportações e o registro do bot que citam o código. O código entra em `dados/lgpd_esquecidos.json`: restaurar uma
cópia antiga da memória apaga de novo. Não há mapa código → nome aqui (ele só existe na versão offline do Rickson).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from quiron.nucleo.config import pasta_dados
from quiron.servicos.planejamento.ficha import codigo


@dataclass
class Apagado:
    cliente: str
    itens: dict[str, int] = field(default_factory=dict)
    aviso: str = ""

    @property
    def total(self) -> int:
        return sum(self.itens.values())

    def descrever(self) -> str:
        if not self.total:
            return f"Nada guardado sobre {self.cliente}." + (f"\n⚠️ {self.aviso}" if self.aviso else "")
        partes = [f"{n} {nome}" for nome, n in self.itens.items() if n]
        return f"🧹 {self.cliente} esquecido: " + ", ".join(partes) + "." + (f"\n⚠️ {self.aviso}" if self.aviso else "")


def _cita(texto: str, cod: str) -> bool:
    """O código aparece inteiro (CLI-01 não apaga CLI-012)."""
    return re.search(rf"(?<![A-Za-z0-9-]){re.escape(cod)}(?![A-Za-z0-9])", texto or "", re.I) is not None


def esquecer_cliente(cliente: str) -> Apagado:
    cod = codigo(cliente)
    raiz = pasta_dados()
    r = Apagado(cod)

    fichas = [p for p in (raiz / "fichas").glob(f"{cod}.json")] + list((raiz / "fichas" / "historico").glob(f"{cod}-*.json"))
    for p in fichas:
        p.unlink()
    r.itens["fichas/versões"] = len(fichas)

    carteiras: list[str] = []
    for p in (raiz / "carteiras").glob("CART-*.json"):
        try:
            if _cita(p.read_text(encoding="utf-8"), cod):
                p.unlink()
                carteiras.append(p.stem)
        except (OSError, json.JSONDecodeError):
            continue
    r.itens["carteiras"] = len(carteiras)

    r.itens["relatórios"] = _apagar_relatorios(raiz / "analise.db", cod, carteiras)
    pasta_reunioes = raiz / "reunioes" / cod
    r.itens["anotações de reunião"] = len(list(pasta_reunioes.glob("*.json"))) if pasta_reunioes.exists() else 0
    shutil.rmtree(pasta_reunioes, ignore_errors=True)
    r.itens["lembretes"] = _apagar_lembretes(raiz / "agenda.db", cod)
    r.itens["tarefas/notas/metas"] = _apagar_organizacao(raiz / "organizacao.db", cod)
    r.itens["teses, treinos e ideias"] = (
        _apagar_linhas(raiz / "carreira.db", cod, {"teses": ["titulo", "tese", "ativo", "premissas", "invalidacao", "aprendizado"],
                                                   "revisoes_teses": ["nota"], "entrevistas": ["mensagens", "feedback"],
                                                   "portfolio": ["comentario"]})
        + _apagar_linhas(raiz / "treino.db", cod, {"sessoes": ["mensagens", "feedback", "cenario"]})
        + _apagar_linhas(raiz / "conteudo.db", cod, {"ideias": ["titulo", "angulo", "fontes"]}, fts={"ideias": ("ideias_busca", ["titulo", "angulo"])}))
    r.itens["mensagens de conversa"] = _apagar_conversas(raiz / "conversas.db", cod)
    from quiron.runtime.memoria_longa import MemoriaLonga

    memoria = MemoriaLonga()
    r.itens["memória persistente (fatos, conversas resumidas, eventos)"] = memoria.apagar_por_cliente(cod)
    r.itens["cópias da memória"] = _apagar_das_copias(memoria.pasta_copias(), cod)
    r.itens["exportações e registro do bot"] = _apagar_exportacoes(raiz, cod)
    _anotar_esquecido(raiz, cod)

    n = 0
    ws = raiz / "workspace"
    for arq in [ws / "MEMORIA.md", *sorted((ws / "diario").glob("*.md"))]:
        if not arq.exists():
            continue
        linhas = arq.read_text(encoding="utf-8").splitlines()
        restantes = [l for l in linhas if not _cita(l, cod)]
        if len(restantes) != len(linhas):
            n += len(linhas) - len(restantes)
            arq.write_text("\n".join(restantes) + "\n", encoding="utf-8")
    r.itens["linhas de memória/diário"] = n
    from quiron.servicos.offline import cofre

    if cofre.existe():
        r.aviso = f"o nome real fica no cofre da versão offline (criptografado): no PC, rode `uv run quiron-offline cofre remover {cod}`."
    return r


def _relatorio_cita(pasta: str | None, cod: str) -> bool:
    if not pasta or not Path(pasta).exists():
        return False
    for nome in ("relatorio.json", "relatorio.md"):
        arq = Path(pasta) / nome
        try:
            if arq.exists() and _cita(arq.read_text(encoding="utf-8", errors="replace"), cod):
                return True
        except OSError:
            continue
    return False


def _apagar_relatorios(banco: Path, cod: str, carteiras: list[str] | None = None) -> int:
    if not banco.exists():
        return 0
    con = sqlite3.connect(banco)
    try:
        alvos = [cod, *(carteiras or [])]  # análise de carteira só guarda o CART-…: o cliente estava dentro do arquivo
        linhas = [(i, p) for i, p, *textos in con.execute("SELECT id, pasta, parametros, titulo, resumo FROM tarefas")
                  if any(_cita(t, a) for t in textos for a in alvos) or _relatorio_cita(p, cod)]
        for ident, pasta in linhas:
            if pasta and Path(pasta).exists():
                shutil.rmtree(pasta, ignore_errors=True)
            con.execute("DELETE FROM tarefas WHERE id = ?", (ident,))
            con.execute("DELETE FROM busca_relatorios WHERE tarefa_id = ?", (ident,))
        con.commit()
        return len(linhas)
    finally:
        con.close()


def _apagar_organizacao(banco: Path, cod: str) -> int:
    if not banco.exists():
        return 0
    con = sqlite3.connect(banco)
    try:
        n = 0
        for tabela in ("tarefas", "notas", "metas"):
            ids = [i for i, t in con.execute(f"SELECT id, texto FROM {tabela} WHERE texto LIKE ?", (f"%{cod}%",)) if _cita(t, cod)]
            con.executemany(f"DELETE FROM {tabela} WHERE id = ?", [(i,) for i in ids])  # o gatilho limpa a busca das notas
            if tabela == "metas":
                con.executemany("DELETE FROM metas_registros WHERE meta = ?", [(i,) for i in ids])
            n += len(ids)
        regs = [i for i, t in con.execute("SELECT id, nota FROM metas_registros WHERE nota LIKE ?", (f"%{cod}%",)) if _cita(t, cod)]
        con.executemany("UPDATE metas_registros SET nota = '' WHERE id = ?", [(i,) for i in regs])
        n += len(regs)
        con.commit()
        return n
    finally:
        con.close()


def _apagar_lembretes(banco: Path, cod: str) -> int:
    if not banco.exists():
        return 0
    con = sqlite3.connect(banco)
    try:
        ids = [i for i, t in con.execute("SELECT id, texto FROM agendamentos WHERE texto LIKE ?", (f"%{cod}%",)) if _cita(t, cod)]
        con.executemany("DELETE FROM agendamentos WHERE id = ?", [(i,) for i in ids])
        con.commit()
        return len(ids)
    finally:
        con.close()


def _apagar_conversas(banco: Path, cod: str) -> int:
    if not banco.exists():
        return 0
    con = sqlite3.connect(banco)
    try:
        ids = [i for i, t in con.execute("SELECT id, texto FROM mensagens WHERE texto LIKE ?", (f"%{cod}%",)) if _cita(t, cod)]
        con.executemany("DELETE FROM mensagens WHERE id = ?", [(i,) for i in ids])
        n = len(ids)
        chats = [c for c, t in con.execute("SELECT chat, resumo FROM resumos WHERE resumo LIKE ?", (f"%{cod}%",)) if _cita(t, cod)]
        con.executemany("DELETE FROM resumos WHERE chat = ?", [(c,) for c in chats])
        if n:
            con.execute("INSERT INTO mensagens_busca(mensagens_busca) VALUES('rebuild')")
        con.commit()
        return n
    finally:
        con.close()


def _apagar_linhas(banco: Path, cod: str, tabelas: dict[str, list[str]],
                   fts: dict[str, tuple[str, list[str]]] | None = None) -> int:
    """Apaga as linhas cujas colunas de texto citam o código (nomes de tabela/coluna fixos, deste módulo)."""
    if not banco.exists():
        return 0
    con = sqlite3.connect(banco)
    try:
        existentes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        n = 0
        for tabela, colunas in tabelas.items():
            if tabela not in existentes:
                continue
            chave = "tarefa" if tabela == "portfolio" else "id"
            linhas = [row for row in con.execute(f"SELECT {chave}, {', '.join(colunas)} FROM {tabela}")
                      if any(_cita(str(v or ""), cod) for v in row[1:])]
            if fts and tabela in fts:  # índice de busca sem gatilho de DELETE: tira à mão
                virtual, cols_fts = fts[tabela]
                for row in linhas:
                    valores = [row[1 + colunas.index(c)] for c in cols_fts]
                    con.execute(f"INSERT INTO {virtual}({virtual}, rowid, {', '.join(cols_fts)}) VALUES ('delete', ?, "
                                f"{', '.join('?' * len(cols_fts))})", (row[0], *valores))
            con.executemany(f"DELETE FROM {tabela} WHERE {chave} = ?", [(row[0],) for row in linhas])
            n += len(linhas)
        con.commit()
        return n
    finally:
        con.close()


def _apagar_das_copias(pasta: Path, cod: str) -> int:
    """As cópias diárias da memória (e as "antes de restaurar") também esquecem — senão restaurar traria o cliente de volta."""
    import tempfile

    from quiron.runtime.memoria_longa import MemoriaLonga

    if not pasta.exists():
        return 0
    n = 0
    for copia in sorted(p for p in pasta.iterdir() if p.is_dir()):
        if (copia / "memoria.db").exists():
            with tempfile.TemporaryDirectory() as tmp:
                m = MemoriaLonga(copia / "memoria.db", arquivo_md=Path(tmp) / "MEMORIA.md")
                try:
                    n += m.apagar_por_cliente(cod)
                finally:
                    m.con.close()
        n += _apagar_conversas(copia / "conversas.db", cod)
    return n


def _apagar_exportacoes(raiz: Path, cod: str) -> int:
    """Exportações JSON da memória e o registro do bot (dados/logs/telegram.log*)."""
    n = 0
    for arq in sorted((raiz / "exportacoes").glob("memoria-*.json")):
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mudou = False
        for chave, itens in list(dados.items()):
            if isinstance(itens, list):
                restantes = [x for x in itens if not _cita(json.dumps(x, ensure_ascii=False), cod)]
                if len(restantes) != len(itens):
                    n += len(itens) - len(restantes)
                    dados[chave], mudou = restantes, True
        if mudou:
            arq.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    for arq in sorted((raiz / "logs").glob("*.log*")):
        try:
            linhas = arq.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        restantes = [l for l in linhas if not _cita(l, cod)]
        if len(restantes) != len(linhas):
            n += len(linhas) - len(restantes)
            try:
                arq.write_text("\n".join(restantes) + "\n", encoding="utf-8")
            except OSError:
                pass  # Windows com o log aberto pelo bot: fica para a próxima
    return n


def _anotar_esquecido(raiz: Path, cod: str) -> None:
    arq = raiz / "lgpd_esquecidos.json"
    try:
        lista = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else []
    except (OSError, json.JSONDecodeError):
        lista = []
    if cod not in lista:
        arq.write_text(json.dumps(sorted([*lista, cod])), encoding="utf-8")


def esquecidos() -> list[str]:
    arq = pasta_dados() / "lgpd_esquecidos.json"
    try:
        return list(json.loads(arq.read_text(encoding="utf-8"))) if arq.exists() else []
    except (OSError, json.JSONDecodeError):
        return []
