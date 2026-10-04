"""`uv run quiron-academia <comando>` — manutenção da Academia pelo terminal.

  status                       painel de progresso e tamanho do banco
  gerar --modulo 3 --n 8       gera questões novas (revisadas) para um módulo (ou --todos)
  cards --topico 6.2.1         gera flashcards de um tópico
  semear                       importa o banco inicial de questões (config/academia/banco_inicial_cfp.json)
  exportar ARQUIVO             exporta as questões do banco (para virar banco inicial)
  mapear-cfp PROGRAMA.txt      regera config/editais/CFP.yaml a partir do texto do Programa Detalhado
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

from quiron.nucleo.config import PASTA_CONFIG
from quiron.servicos.academia import diagnostico, edital, estudo, gerador
from quiron.servicos.academia.banco import Banco

SEMENTE = PASTA_CONFIG / "academia" / "banco_inicial_cfp.json"


def semear(banco: Banco | None = None, arquivo: Path = SEMENTE) -> int:
    """Importa questões de um JSON (ignora as que já existem pelo enunciado). Devolve quantas entraram."""
    banco = banco or Banco()
    if not arquivo.exists():
        return 0
    existentes = set()
    for m in edital.modulos("CFP"):
        existentes |= set(banco.enunciados("CFP", str(m["numero"])))
    novas = 0
    for q in json.loads(arquivo.read_text(encoding="utf-8")):
        if q["enunciado"] in existentes:
            continue
        banco.adicionar_questao(q.get("cert", "CFP"), q["modulo"], q["topico"], q["enunciado"], q["alternativas"],
                                q["correta"], q["explicacao"], q.get("fontes"), q.get("dificuldade", "media"),
                                "banco inicial", q.get("modelo", ""), q.get("revisor", ""))
        novas += 1
    return novas


def exportar(destino: Path, banco: Banco | None = None) -> int:
    banco = banco or Banco()
    with banco._con() as c:  # noqa: SLF001
        rows = c.execute("SELECT * FROM questoes WHERE anulada=0 ORDER BY modulo, topico, id").fetchall()
    itens = [{"cert": r["cert"], "modulo": r["modulo"], "topico": r["topico"], "enunciado": r["enunciado"],
              "alternativas": json.loads(r["alternativas"]), "correta": r["correta"], "explicacao": r["explicacao"],
              "fontes": json.loads(r["fontes"]), "dificuldade": r["dificuldade"], "modelo": r["modelo"],
              "revisor": r["revisor"]} for r in rows]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(itens)


def main() -> None:
    p = argparse.ArgumentParser(description="Academia do Quíron")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    g = sub.add_parser("gerar")
    g.add_argument("--modulo", type=int)
    g.add_argument("--todos", action="store_true")
    g.add_argument("--n", type=int, default=8)
    g.add_argument("--pausa", type=float, default=20, help="segundos entre lotes (respeita o limite grátis)")
    c = sub.add_parser("cards")
    c.add_argument("--topico", required=True)
    c.add_argument("--n", type=int, default=6)
    sub.add_parser("semear")
    e = sub.add_parser("exportar")
    e.add_argument("arquivo", type=Path)
    m = sub.add_parser("mapear-cfp")
    m.add_argument("programa", type=Path)
    a = p.parse_args()
    banco = Banco()

    if a.cmd == "status":
        print(diagnostico.painel(banco))
    elif a.cmd == "gerar":
        modulos = [x["numero"] for x in edital.modulos("CFP")] if a.todos else [a.modulo]
        if not modulos or modulos == [None]:
            raise SystemExit("Informe --modulo N ou --todos")
        for mod in modulos:
            feitas = 0
            for alvo in gerador.topicos_para_gerar(mod, a.n, "CFP", banco):
                if feitas >= a.n:
                    break
                try:
                    r = gerador.gerar_questoes(alvo, estudo.POR_LOTE, "CFP", banco)
                except Exception as ex:  # noqa: BLE001
                    print(f"  {alvo}: falhou ({type(ex).__name__}); pausa longa")
                    time.sleep(a.pausa * 3)
                    continue
                feitas += len(r["gravadas"])
                print(f"M{mod} {alvo}: +{len(r['gravadas'])} (recusadas {len(r['recusadas'])}) via {r.get('modelo')}")
                time.sleep(a.pausa)
        print(diagnostico.painel(banco))
    elif a.cmd == "cards":
        print(f"{len(gerador.gerar_flashcards(a.topico, a.n, 'CFP', banco))} flashcards criados.")
    elif a.cmd == "semear":
        print(f"{semear(banco)} questões importadas do banco inicial.")
    elif a.cmd == "exportar":
        print(f"{exportar(a.arquivo, banco)} questões exportadas para {a.arquivo}.")
    elif a.cmd == "mapear-cfp":
        dados = edital.extrair_programa(a.programa.read_text(encoding="utf-8"))
        atual = edital.carregar("CFP") if (edital.PASTA_EDITAIS / "CFP.yaml").exists() else {}
        cab = {k: v for k, v in atual.items() if k != "modulos"}
        antigos = {m["numero"]: m for m in atual.get("modulos", [])}
        for mod in dados["modulos"]:
            mod.update({k: v for k, v in antigos.get(mod["numero"], {}).items() if k in {"tempo_min", "questoes_estimadas"}})
        (edital.PASTA_EDITAIS / "CFP.yaml").write_text(
            yaml.safe_dump({**cab, "modulos": dados["modulos"]}, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
        print(f"{sum(len(x['topicos']) for x in dados['modulos'])} tópicos em {len(dados['modulos'])} módulos.")
