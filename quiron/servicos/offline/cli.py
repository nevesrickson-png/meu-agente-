"""`uv run quiron-offline …` — versão offline do Quíron no PC.

  verificar                 confere Ollama, modelo, biblioteca, embeddings, cofre e memória do PC
  pacote                    gera o pacote de dados (no servidor 24h ou no PC principal)
  importar <arquivo>        importa o pacote no PC offline
  baixar <https://…ts.net>  baixa o pacote do Terminal do servidor (pede a TERMINAL_SENHA) e importa
  cofre criar | listar | adicionar CLI-012 "Nome" | remover CLI-012 | trocar-senha
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import httpx

from quiron.nucleo import offline
from quiron.nucleo.config import carregar_config, pasta_biblioteca, pasta_dados


def verificar() -> list[tuple[str, bool, str]]:
    itens: list[tuple[str, bool, str]] = []
    cfg = offline.config()
    try:
        tags = httpx.get(offline.ollama_url() + "/api/tags", timeout=5).json()
        nomes = [m["name"] for m in tags.get("models", [])]
        itens.append(("Ollama rodando", True, offline.ollama_url()))
        alvo = offline.modelo().split("/", 1)[1]
        tem = any(n == alvo or n.split(":")[0] == alvo for n in nomes)
        itens.append((f"Modelo {alvo}", tem, "pronto" if tem else f"rode no Prompt: ollama pull {alvo}"))
    except (httpx.HTTPError, ValueError):
        itens.append(("Ollama rodando", False, "instale em ollama.com/download e abra o Ollama"))
    indice = pasta_biblioteca() / "indice"
    itens.append(("Índice da biblioteca", indice.exists() and any(indice.iterdir()),
                  str(indice) if indice.exists() else "importe o pacote (quiron-offline importar)"))
    modelos = pasta_dados() / "modelos"
    emb = os.environ.get("QUIRON_EMBEDDINGS", "fastembed") == "lexico" or (modelos.exists() and any(modelos.glob("models--*")))
    itens.append(("Modelo de embeddings local", emb, "ok" if emb else "vem no pacote (dados/modelos)"))
    from quiron.servicos.offline import cofre

    itens.append(("Cofre de clientes", cofre.existe(), str(cofre.caminho()) if cofre.existe() else "crie com: quiron-offline cofre criar"))
    try:
        import psutil

        livre = psutil.virtual_memory().available / 1e9
        itens.append(("Memória livre", livre >= 3.5, f"{livre:.1f} GB (o modelo de 3B usa ~2,5 GB)"))
    except ImportError:
        pass
    itens.append(("Contexto do modelo", True, f"{cfg.get('contexto_tokens', 8192)} tokens · {cfg.get('passos_agente', 5)} passos"))
    return itens


def _cofre(args: list[str]) -> None:
    from quiron.servicos.offline import cofre

    os.environ["QUIRON_MODO"] = "offline"
    carregar_config.cache_clear()
    acao = args[0] if args else "listar"
    if acao == "criar":
        s1 = getpass.getpass("Crie a senha do cofre (mín. 10 caracteres; sem ela não há recuperação): ")
        if s1 != getpass.getpass("Repita: "):
            sys.exit("As senhas não conferem.")
        cofre.criar(s1)
        print(f"✅ Cofre criado em {cofre.caminho()}")
        return
    c = cofre.abrir(getpass.getpass("Senha do cofre: "))
    if acao == "listar":
        for x in sorted(c.clientes.values(), key=lambda x: x.nome):
            print(f"{x.codigo}  {x.nome}  {x.telefone}")
        print(f"{len(c.clientes)} cliente(s).")
    elif acao == "adicionar" and len(args) >= 3:
        print(f"✅ {c.gravar(args[1], nome=' '.join(args[2:])).codigo} gravado.")
    elif acao == "remover" and len(args) >= 2:
        print("Removido." if c.remover(args[1]) else "Não estava no cofre.")
    elif acao == "trocar-senha":
        nova = getpass.getpass("Nova senha: ")
        if nova != getpass.getpass("Repita: "):
            sys.exit("As senhas não conferem.")
        c.trocar_senha(nova)
        print("✅ Senha trocada.")
    else:
        sys.exit(__doc__)


def baixar(url: str) -> Path:
    senha = getpass.getpass("Senha do Terminal do servidor (TERMINAL_SENHA): ")
    destino = pasta_dados() / "exportacoes" / "quiron-offline-baixado.tar.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=url.rstrip("/"), timeout=600, follow_redirects=True) as http:
        r = http.post("/login", data={"senha": senha})
        if r.status_code >= 400 or "quiron_sessao" not in {c.name for c in http.cookies.jar}:
            sys.exit("Senha recusada pelo Terminal do servidor.")
        with http.stream("GET", "/api/offline/pacote", headers={"X-Quiron": "terminal"}) as resp:
            resp.raise_for_status()
            with destino.open("wb") as f:
                for parte in resp.iter_bytes():
                    f.write(parte)
    return destino


def main() -> None:
    p = argparse.ArgumentParser(prog="quiron-offline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("acao", choices=["verificar", "pacote", "importar", "baixar", "cofre"])
    p.add_argument("resto", nargs="*")
    a = p.parse_args()
    from quiron.servicos.offline import pacote

    if a.acao == "verificar":
        itens = verificar()
        for nome, ok, info in itens:
            print(f"{'✅' if ok else '❌'} {nome}: {info}")
        sys.exit(0 if all(ok for n, ok, _ in itens if n in {"Ollama rodando"} or n.startswith("Modelo ")) else 1)
    if a.acao == "pacote":
        print(f"📦 Pacote gerado: {pacote.gerar()}")
    elif a.acao == "importar":
        if not a.resto:
            sys.exit("Informe o arquivo .tar.gz do pacote.")
        r = pacote.importar(Path(a.resto[0]))
        print(f"✅ {r['arquivos']} arquivo(s) importados: {', '.join(r['itens'])}" + (f"\nO que havia antes foi guardado em {r['reserva']}" if r["reserva"] else ""))
    elif a.acao == "baixar":
        if not a.resto:
            sys.exit("Informe o endereço do Terminal do servidor (ex.: https://quiron.tail1234.ts.net).")
        arq = baixar(a.resto[0])
        r = pacote.importar(arq)
        print(f"✅ Baixado e importado ({r['arquivos']} arquivos).")
    elif a.acao == "cofre":
        _cofre(a.resto)
