"""Conferência de compliance em textos (mensagens para clientes, falas do treino, transcrições de reunião).

Regras por expressão — indicação para revisar, não parecer jurídico. Base: Resolução CVM 178 (assessor), Código ANBIMA
de Distribuição (sem promessa de rentabilidade; rentabilidade passada com ressalva), LGPD (dados pessoais)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class Alerta:
    regra: str
    gravidade: str  # grave | atencao
    trecho: str
    sugestao: str

    def descrever(self) -> str:
        return f"{'⛔' if self.gravidade == 'grave' else '⚠️'} {self.regra}: “{self.trecho}” → {self.sugestao}"


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


REGRAS: list[tuple[str, str, str, str]] = [
    # (regra, gravidade, padrão sobre o texto sem acento, sugestão)
    ("Promessa de rentabilidade", "grave",
     r"\bgarant\w*\b[^.?!]{0,40}\b(rend\w*|retorno|lucro|ganho|rentabilidade|valoriza\w*)|(rend\w*|retorno|lucro|ganho|rentabilidade)[^.?!]{0,25}\bgarantid[oa]s?\b",
     "não prometa retorno; diga o que é contratado (ex.: taxa do título) e os riscos"),
    ("Negar o risco", "grave", r"\bsem (nenhum )?risco\b|\brisco zero\b|\bnao tem (como|risco de) perder\b|\bnao (vai|tem como) dar errado\b|\bdinheiro certo\b",
     "todo investimento tem algum risco (crédito, mercado, liquidez); explique qual"),
    ("Certeza sobre o futuro", "grave", r"\bcom certeza (vai|sobe|rende|valoriza)\w*|\bvai (subir|valorizar|bombar) com certeza\b|\bpode confiar que (vai|sobe)",
     "use cenários e probabilidades, não certezas"),
    ("Promessa", "atencao", r"\bprometo\b|\bprometer\b", "evite prometer resultado; comprometa-se com o processo (acompanhar, revisar)"),
    ("Rentabilidade passada sem ressalva", "atencao", r"\b(rendeu|subiu|valorizou|entregou)\b[^.?!]{0,30}\d+[,.]?\d*\s*%",
     "inclua: rentabilidade passada não é garantia de rentabilidade futura"),
    ("FGC exagerado", "grave", r"\bfgc\b[^.?!]{0,40}\b(qualquer valor|sem limite|tudo|integral)\b",
     "FGC cobre até R$ 250 mil por CPF por instituição (teto global de R$ 1 milhão a cada 4 anos)"),
    ("Superlativo", "atencao", r"\bmelhor investimento\b|\binvestimento perfeito\b|\bimperdivel\b|\boportunidade unica\b",
     "troque por por que faz sentido para o objetivo e o perfil do cliente"),
    ("Pressão por decisão", "atencao", r"\bso hoje\b|\bultima chance\b|\bcorre(r)? que\b|\bfecha (hoje|agora) senao\b",
     "dê tempo para o cliente decidir; urgência só se for real (ex.: vencimento de oferta)"),
]
SENSIVEIS = [
    ("CPF no texto", r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    ("Telefone no texto", r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"),
    ("E-mail no texto", r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
]


def conferir(texto: str, dados_pessoais: bool = True) -> list[Alerta]:
    """Alertas de compliance encontrados no texto (vazio = nada óbvio)."""
    if not texto:
        return []
    norm = _norm(texto)
    alertas = []
    for regra, grav, padrao, sug in REGRAS:
        for m in re.finditer(padrao, norm):
            if regra == "Rentabilidade passada sem ressalva" and re.search(r"(passad\w* nao|nao (e|eh) garantia|nao garante)", norm):
                continue
            if re.search(r"\bnao( e| eh| ha| tem| existe)?( nenhuma?)?\s*$", norm[max(0, m.start() - 16):m.start()]):
                continue  # negação: "não é garantia de rentabilidade", "não garantimos retorno"
            alertas.append(Alerta(regra, grav, texto[max(0, m.start() - 15):m.end() + 15].strip(), sug))
            break  # um alerta por regra basta
    if dados_pessoais:
        for regra, padrao in SENSIVEIS:
            if m := re.search(padrao, texto):
                alertas.append(Alerta(regra, "grave", m.group(0), "LGPD: não coloque dados pessoais; use o código CLI-XXX"))
    return alertas


def resumo(alertas: list[Alerta]) -> str:
    if not alertas:
        return "✅ Compliance: nada óbvio a corrigir (revise mesmo assim)."
    return "Compliance — revisar antes de enviar:\n" + "\n".join(a.descrever() for a in alertas)
