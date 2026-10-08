"""Banco da Academia (`dados/academia.db`): questões, respostas, flashcards, simulados e preferências de estudo.

Revisão espaçada (SM-2 simplificado) vale para flashcards e também para questões erradas: o que você erra volta
em 1, 3, 7… dias até acertar com folga.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from quiron.nucleo.banco import conectar as conectar_banco
from quiron.nucleo.config import pasta_dados

LETRAS = "ABCD"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS questoes (
  id INTEGER PRIMARY KEY, cert TEXT NOT NULL, modulo INTEGER NOT NULL, topico TEXT NOT NULL,
  enunciado TEXT NOT NULL, alternativas TEXT NOT NULL, correta INTEGER NOT NULL, explicacao TEXT NOT NULL,
  fontes TEXT NOT NULL DEFAULT '[]', dificuldade TEXT DEFAULT 'media', origem TEXT DEFAULT 'gerada',
  modelo TEXT DEFAULT '', revisor TEXT DEFAULT '', criada_em TEXT NOT NULL, anulada INTEGER DEFAULT 0, motivo_anulacao TEXT DEFAULT '',
  -- revisão espaçada da própria questão
  intervalo REAL DEFAULT 0, facilidade REAL DEFAULT 2.5, repeticoes INTEGER DEFAULT 0, revisar_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_q_mod ON questoes(cert, modulo, topico);
CREATE TABLE IF NOT EXISTS respostas (
  id INTEGER PRIMARY KEY, questao_id INTEGER NOT NULL REFERENCES questoes(id), escolha INTEGER NOT NULL,
  acertou INTEGER NOT NULL, quando TEXT NOT NULL, contexto TEXT DEFAULT 'questoes'
);
CREATE INDEX IF NOT EXISTS ix_r_q ON respostas(questao_id);
CREATE TABLE IF NOT EXISTS flashcards (
  id INTEGER PRIMARY KEY, cert TEXT NOT NULL, modulo INTEGER NOT NULL, topico TEXT NOT NULL,
  frente TEXT NOT NULL, verso TEXT NOT NULL, fontes TEXT DEFAULT '[]', criada_em TEXT NOT NULL,
  intervalo REAL DEFAULT 0, facilidade REAL DEFAULT 2.5, repeticoes INTEGER DEFAULT 0, revisar_em TEXT NOT NULL,
  suspenso INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS revisoes_cards (id INTEGER PRIMARY KEY, card_id INTEGER, nota INTEGER, quando TEXT);
CREATE TABLE IF NOT EXISTS simulados (
  id INTEGER PRIMARY KEY, cert TEXT NOT NULL, questoes TEXT NOT NULL, posicao INTEGER DEFAULT 0,
  iniciado_em TEXT NOT NULL, terminado_em TEXT, tipo TEXT DEFAULT 'mini'
);
CREATE TABLE IF NOT EXISTS preferencias (chave TEXT PRIMARY KEY, valor TEXT);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Questao:
    id: int
    cert: str
    modulo: int
    topico: str
    enunciado: str
    alternativas: list[str]
    correta: int
    explicacao: str
    fontes: list[str] = field(default_factory=list)
    dificuldade: str = "media"
    origem: str = "gerada"
    modelo: str = ""
    revisor: str = ""

    @property
    def mesmo_revisor(self) -> bool:
        return bool(self.modelo) and self.modelo == self.revisor

    @property
    def letra_correta(self) -> str:
        return LETRAS[self.correta]

    def texto(self, numero: str = "") -> str:
        cab = f"{numero} " if numero else ""
        alts = "\n".join(f"{LETRAS[i]}) {a}" for i, a in enumerate(self.alternativas))
        return f"{cab}📝 {self.cert} · Módulo {self.modulo} · tópico {self.topico}\n\n{self.enunciado}\n\n{alts}"


@dataclass
class Flashcard:
    id: int
    modulo: int
    topico: str
    frente: str
    verso: str
    fontes: list[str] = field(default_factory=list)
    cert: str = "CFP"


def proxima_revisao(nota: int, repeticoes: int, intervalo: float, facilidade: float, hoje: date | None = None
                    ) -> tuple[int, float, float, str]:
    """SM-2: nota 0–5 (≥3 = lembrou). Devolve (repetições, intervalo em dias, facilidade, data da próxima revisão)."""
    hoje = hoje or date.today()
    if nota < 3:
        repeticoes, intervalo = 0, 1.0
    else:
        repeticoes += 1
        intervalo = 1.0 if repeticoes == 1 else 3.0 if repeticoes == 2 else round(intervalo * facilidade, 1)
    facilidade = max(1.3, facilidade + 0.1 - (5 - nota) * (0.08 + (5 - nota) * 0.02))
    return repeticoes, intervalo, facilidade, (hoje + timedelta(days=intervalo)).isoformat()


class Banco:
    def __init__(self, caminho: Path | None = None):
        self.caminho = caminho or pasta_dados() / "academia.db"
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        con = conectar_banco(self.caminho)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------ preferências
    def pref(self, chave: str, padrao: Any = None) -> Any:
        with self._con() as c:
            r = c.execute("SELECT valor FROM preferencias WHERE chave=?", (chave,)).fetchone()
        return json.loads(r["valor"]) if r else padrao

    def definir_pref(self, chave: str, valor: Any) -> None:
        with self._con() as c:
            c.execute("INSERT OR REPLACE INTO preferencias VALUES (?, ?)", (chave, json.dumps(valor, ensure_ascii=False)))

    # ------------------------------------------------------------ questões
    def adicionar_questao(self, cert: str, modulo: int, topico: str, enunciado: str, alternativas: list[str], correta: int,
                          explicacao: str, fontes: list[str] | None = None, dificuldade: str = "media",
                          origem: str = "gerada", modelo: str = "", revisor: str = "") -> int:
        if len(alternativas) != 4 or not 0 <= correta < 4:
            raise ValueError("questão precisa de 4 alternativas e uma correta (0–3)")
        with self._con() as c:
            cur = c.execute(
                "INSERT INTO questoes (cert, modulo, topico, enunciado, alternativas, correta, explicacao, fontes, "
                "dificuldade, origem, modelo, revisor, criada_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cert, modulo, topico, enunciado, json.dumps(alternativas, ensure_ascii=False), correta, explicacao,
                 json.dumps(fontes or [], ensure_ascii=False), dificuldade, origem, modelo, revisor, _agora()))
            return int(cur.lastrowid)

    @staticmethod
    def _q(r: sqlite3.Row) -> Questao:
        return Questao(r["id"], r["cert"], r["modulo"], r["topico"], r["enunciado"], json.loads(r["alternativas"]),
                       r["correta"], r["explicacao"], json.loads(r["fontes"]), r["dificuldade"], r["origem"], r["modelo"], r["revisor"])

    def questao(self, qid: int) -> Questao | None:
        with self._con() as c:
            r = c.execute("SELECT * FROM questoes WHERE id=?", (qid,)).fetchone()
        return self._q(r) if r else None

    def enunciados(self, cert: str, topico_prefixo: str) -> list[str]:
        """Enunciados já existentes num tópico (para o gerador não repetir)."""
        with self._con() as c:
            rows = c.execute("SELECT enunciado FROM questoes WHERE cert=? AND (topico=? OR topico LIKE ?)",
                             (cert, topico_prefixo, topico_prefixo + ".%")).fetchall()
        return [r["enunciado"] for r in rows]

    def contar_questoes(self, cert: str = "CFP") -> dict[int, int]:
        with self._con() as c:
            rows = c.execute("SELECT modulo, COUNT(*) n FROM questoes WHERE cert=? AND anulada=0 GROUP BY modulo",
                             (cert,)).fetchall()
        return {r["modulo"]: r["n"] for r in rows}

    def contar_por_topico(self, cert: str, modulo: int) -> dict[str, int]:
        with self._con() as c:
            rows = c.execute("SELECT topico, COUNT(*) n FROM questoes WHERE cert=? AND modulo=? AND anulada=0 GROUP BY topico",
                             (cert, modulo)).fetchall()
        return {r["topico"]: r["n"] for r in rows}

    def escolher_questoes(self, cert: str, n: int, *, modulo: int | None = None, topico: str | None = None,
                          excluir: set[int] | None = None, hoje: date | None = None) -> list[Questao]:
        """Ordem: revisões vencidas (erradas antes) → nunca respondidas → as respondidas há mais tempo."""
        hoje = (hoje or date.today()).isoformat()
        filtros, args = ["q.cert=?", "q.anulada=0"], [cert]
        if modulo is not None:
            filtros.append("q.modulo=?")
            args.append(modulo)
        if topico:
            filtros.append("(q.topico=? OR q.topico LIKE ?)")
            args += [topico, topico + ".%"]
        sql = f"""
          SELECT q.*, MAX(r.quando) ultima, COUNT(r.id) vezes FROM questoes q LEFT JOIN respostas r ON r.questao_id=q.id
          WHERE {' AND '.join(filtros)} GROUP BY q.id
          ORDER BY CASE WHEN q.revisar_em IS NOT NULL AND q.revisar_em <= ? THEN 0 WHEN COUNT(r.id)=0 THEN 1 ELSE 2 END,
                   q.revisar_em, ultima, RANDOM()"""
        with self._con() as c:
            rows = c.execute(sql, [*args, hoje]).fetchall()
        excluir = excluir or set()
        return [self._q(r) for r in rows if r["id"] not in excluir][:n]

    def responder(self, qid: int, escolha: int, contexto: str = "questoes", hoje: date | None = None) -> bool:
        q = self.questao(qid)
        if not q:
            raise KeyError(qid)
        acertou = escolha == q.correta
        with self._con() as c:
            c.execute("INSERT INTO respostas (questao_id, escolha, acertou, quando, contexto) VALUES (?,?,?,?,?)",
                      (qid, escolha, int(acertou), _agora(), contexto))
            r = c.execute("SELECT repeticoes, intervalo, facilidade FROM questoes WHERE id=?", (qid,)).fetchone()
            rep, inter, fac, prox = proxima_revisao(4 if acertou else 1, r["repeticoes"], r["intervalo"], r["facilidade"], hoje)
            # acerto de primeira em questão nova não precisa voltar logo: só entra na fila quando já errou um dia
            ja_errou = c.execute("SELECT 1 FROM respostas WHERE questao_id=? AND acertou=0 LIMIT 1", (qid,)).fetchone()
            c.execute("UPDATE questoes SET repeticoes=?, intervalo=?, facilidade=?, revisar_em=? WHERE id=?",
                      (rep, inter, fac, prox if ja_errou else None, qid))
        return acertou

    def anular(self, qid: int, motivo: str = "marcada com erro pelo Rickson") -> None:
        with self._con() as c:
            c.execute("UPDATE questoes SET anulada=1, motivo_anulacao=? WHERE id=?", (motivo, qid))

    def desempenho(self, cert: str = "CFP", desde: str | None = None) -> list[dict[str, Any]]:
        """Uma linha por resposta (módulo, tópico, acertou, quando) — base do diagnóstico."""
        sql = ("SELECT q.modulo, q.topico, r.acertou, r.quando, r.contexto FROM respostas r JOIN questoes q ON q.id=r.questao_id "
               "WHERE q.cert=? AND q.anulada=0" + (" AND r.quando >= ?" if desde else "") + " ORDER BY r.quando")
        with self._con() as c:
            return [dict(r) for r in c.execute(sql, (cert, desde) if desde else (cert,)).fetchall()]

    def revisoes_vencidas(self, cert: str = "CFP", hoje: date | None = None) -> int:
        with self._con() as c:
            return c.execute("SELECT COUNT(*) FROM questoes WHERE cert=? AND anulada=0 AND revisar_em <= ?",
                             (cert, (hoje or date.today()).isoformat())).fetchone()[0]

    def dias_estudados(self) -> list[str]:
        with self._con() as c:
            a = c.execute("SELECT DISTINCT substr(quando,1,10) d FROM respostas").fetchall()
            b = c.execute("SELECT DISTINCT substr(quando,1,10) d FROM revisoes_cards").fetchall()
        return sorted({r["d"] for r in [*a, *b]})

    # ------------------------------------------------------------ flashcards
    def adicionar_card(self, cert: str, modulo: int, topico: str, frente: str, verso: str, fontes: list[str] | None = None) -> int:
        with self._con() as c:
            cur = c.execute("INSERT INTO flashcards (cert, modulo, topico, frente, verso, fontes, criada_em, revisar_em) "
                            "VALUES (?,?,?,?,?,?,?,?)", (cert, modulo, topico, frente, verso,
                                                         json.dumps(fontes or [], ensure_ascii=False), _agora(),
                                                         date.today().isoformat()))
            return int(cur.lastrowid)

    def cards_vencidos(self, cert: str | None = "CFP", limite: int = 20, hoje: date | None = None) -> list[Flashcard]:
        """Cards para revisar hoje (cert=None: de todas as áreas)."""
        filtro, args = ("", []) if cert is None else ("cert=? AND ", [cert])
        with self._con() as c:
            rows = c.execute(f"SELECT * FROM flashcards WHERE {filtro}suspenso=0 AND revisar_em <= ? ORDER BY revisar_em, id LIMIT ?",
                             (*args, (hoje or date.today()).isoformat(), limite)).fetchall()
        return [Flashcard(r["id"], r["modulo"], r["topico"], r["frente"], r["verso"], json.loads(r["fontes"]), r["cert"])
                for r in rows]

    def card(self, cid: int) -> Flashcard | None:
        with self._con() as c:
            r = c.execute("SELECT * FROM flashcards WHERE id=?", (cid,)).fetchone()
        return Flashcard(r["id"], r["modulo"], r["topico"], r["frente"], r["verso"], json.loads(r["fontes"]), r["cert"]) if r else None

    def contar_cards(self, cert: str = "CFP") -> int:
        with self._con() as c:
            return c.execute("SELECT COUNT(*) FROM flashcards WHERE cert=? AND suspenso=0", (cert,)).fetchone()[0]

    def revisar_card(self, cid: int, nota: int, hoje: date | None = None) -> str:
        """nota: 0 errei · 3 difícil · 4 bom · 5 fácil. Devolve a data da próxima revisão."""
        with self._con() as c:
            r = c.execute("SELECT repeticoes, intervalo, facilidade FROM flashcards WHERE id=?", (cid,)).fetchone()
            if not r:
                raise KeyError(cid)
            rep, inter, fac, prox = proxima_revisao(nota, r["repeticoes"], r["intervalo"], r["facilidade"], hoje)
            c.execute("UPDATE flashcards SET repeticoes=?, intervalo=?, facilidade=?, revisar_em=? WHERE id=?",
                      (rep, inter, fac, prox, cid))
            c.execute("INSERT INTO revisoes_cards (card_id, nota, quando) VALUES (?,?,?)", (cid, nota, _agora()))
        return prox

    # ------------------------------------------------------------ simulados
    def criar_simulado(self, cert: str, ids: list[int], tipo: str = "mini") -> int:
        with self._con() as c:
            c.execute("UPDATE simulados SET terminado_em=? WHERE terminado_em IS NULL", (_agora(),))  # só um aberto
            cur = c.execute("INSERT INTO simulados (cert, questoes, iniciado_em, tipo) VALUES (?,?,?,?)",
                            (cert, json.dumps(ids), _agora(), tipo))
            return int(cur.lastrowid)

    def simulado(self, sid: int) -> dict[str, Any] | None:
        with self._con() as c:
            r = c.execute("SELECT * FROM simulados WHERE id=?", (sid,)).fetchone()
        return {**dict(r), "questoes": json.loads(r["questoes"])} if r else None

    def avancar_simulado(self, sid: int) -> int:
        with self._con() as c:
            c.execute("UPDATE simulados SET posicao = posicao + 1 WHERE id=?", (sid,))
            return c.execute("SELECT posicao FROM simulados WHERE id=?", (sid,)).fetchone()[0]

    def terminar_simulado(self, sid: int) -> None:
        with self._con() as c:
            c.execute("UPDATE simulados SET terminado_em=? WHERE id=? AND terminado_em IS NULL", (_agora(), sid))

    def respostas_simulado(self, sid: int) -> list[dict[str, Any]]:
        with self._con() as c:
            rows = c.execute("SELECT r.questao_id, r.escolha, r.acertou, q.modulo, q.topico FROM respostas r "
                             "JOIN questoes q ON q.id=r.questao_id WHERE r.contexto=? ORDER BY r.id", (f"simulado:{sid}",)).fetchall()
        return [dict(r) for r in rows]
