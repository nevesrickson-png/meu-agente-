"""Quíron Terminal — backend FastAPI + WebSocket.

- Páginas estáticas em `quiron/terminal/frontend/`.
- `/api/...` devolve os dados de `dados.py` (os mesmos serviços dos MCP).
- `/ws`: a tela assina tópicos (watchlist, curva, notícias…) e o servidor empurra atualizações no intervalo de cada um.
- Por padrão só escuta em 127.0.0.1 (o próprio PC). Com `TERMINAL_SENHA` no .env, pede senha (para o host da Fase 5).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from quiron.nucleo.config import carregar_config, pasta_dados
from quiron.servicos import calculadoras
from quiron.servicos.mercado import bcb
from quiron.terminal.backend import dados

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
COOKIE = "quiron_sessao"

app = FastAPI(title="Quíron Terminal", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- senha (opcional)


def _senha() -> str:
    carregar_config()  # garante o .env carregado
    return os.environ.get("TERMINAL_SENHA", "").split(" #")[0].strip()


def _token(senha: str) -> str:
    return hmac.new(senha.encode(), b"quiron-terminal", hashlib.sha256).hexdigest()


def _autorizado(cookies: dict[str, str]) -> bool:
    senha = _senha()
    return not senha or hmac.compare_digest(cookies.get(COOKIE, ""), _token(senha))


@app.middleware("http")
async def exigir_senha(request: Request, call_next):
    livre = request.url.path in {"/login", "/app.css"} or request.url.path.startswith("/vendor/")
    if not livre and not _autorizado(request.cookies):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"erro": "senha necessária"}, status_code=401)
        return RedirectResponse("/login")
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def pagina_login() -> str:
    return (FRONTEND / "login.html").read_text(encoding="utf-8")


@app.post("/login")
async def fazer_login(request: Request):
    form = await request.form()
    senha = _senha()
    if senha and hmac.compare_digest(str(form.get("senha", "")), senha):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, _token(senha), httponly=True, samesite="strict", max_age=30 * 86400)
        return resp
    return RedirectResponse("/login?erro=1", status_code=303)


# ---------------------------------------------------------------- memo compartilhado entre conexões

_memo: dict[str, tuple[float, Any]] = {}
_travas: dict[str, asyncio.Lock] = {}


async def obter_topico(topico: str, params: dict[str, Any], forcar: bool = False) -> Any:
    if topico not in dados.TOPICOS:
        raise KeyError(topico)
    func, intervalo = dados.TOPICOS[topico]
    chave = json.dumps([topico, params], sort_keys=True, ensure_ascii=False)
    trava = _travas.setdefault(chave, asyncio.Lock())
    async with trava:  # duas abas pedindo o mesmo dado = uma consulta só
        guardado = _memo.get(chave)
        # vale um pouco menos que o intervalo: a atualização agendada sempre encontra o dado vencido e busca de novo
        if guardado and not forcar and time.time() - guardado[0] < intervalo * 0.8:
            return guardado[1]
        valor = await asyncio.to_thread(func, **params)
        if not (isinstance(valor, dict) and valor.get("parcial")):  # resultado parcial não fica guardado
            _memo[chave] = (time.time(), valor)
        return valor


# ---------------------------------------------------------------- API REST


@app.get("/api/topico/{topico}")
async def api_topico(topico: str, request: Request):
    params = dict(request.query_params)
    try:
        return await obter_topico(topico, _converter(topico, params))
    except KeyError:
        raise HTTPException(404, f"tópico desconhecido: {topico}")


def _converter(topico: str, params: dict[str, str]) -> dict[str, Any]:
    inteiros = {"horas", "limite", "dias"}
    return {k: int(v) if k in inteiros else v for k, v in params.items() if v not in ("", None)}


@app.get("/api/calc")
def api_calc_lista() -> dict:
    """Campos de cada calculadora (a tela monta os formulários a partir daqui)."""
    return {k: {"nome": v["nome"], "campos": [list(c) for c in v["campos"]]} for k, v in calculadoras.ESQUEMAS.items()}


@app.post("/api/calc/{nome}")
async def api_calc(nome: str, entrada: dict = Body(...)):
    if nome not in calculadoras.CALCULADORAS:
        raise HTTPException(404, "calculadora desconhecida")
    try:
        if nome == "percentual_cdi" and "cdi_aa" not in entrada:
            entrada = {**entrada, "cdi_aa": (await asyncio.to_thread(bcb.sgs, "cdi", 2)).ultimo.valor}
        return (await asyncio.to_thread(calculadoras.executar, nome, entrada)).como_dict()
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as e:
        return {"erro": f"Entrada inválida: {e}"}


def _arquivo_layouts() -> Path:
    return pasta_dados() / "terminal_layouts.json"


@app.get("/api/layouts")
def ler_layouts() -> dict:
    arq = _arquivo_layouts()
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}


@app.put("/api/layouts/{nome}")
def salvar_layout(nome: str, layout: list = Body(...)) -> dict:
    todos = ler_layouts()
    todos[nome[:40]] = layout
    arq = _arquivo_layouts()
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(todos, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "layouts": list(todos)}


@app.delete("/api/layouts/{nome}")
def apagar_layout(nome: str) -> dict:
    todos = ler_layouts()
    todos.pop(nome, None)
    _arquivo_layouts().write_text(json.dumps(todos, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------- WebSocket


@app.websocket("/ws")
async def ws(socket: WebSocket):
    if not _autorizado(socket.cookies):
        await socket.close(code=4401)
        return
    await socket.accept()
    assinaturas: dict[str, dict] = {}  # id do painel → {topico, params, proximo}

    async def enviar(pid: str, a: dict, forcar: bool = False) -> None:
        try:
            valor = await obter_topico(a["topico"], a["params"], forcar)
            msg = {"id": pid, "topico": a["topico"], "dados": valor}
            if isinstance(valor, dict) and valor.get("parcial"):
                a["proximo"] = time.time() + 4  # volta logo para completar
        except Exception as e:  # noqa: BLE001 — erro de um painel não derruba a conexão
            msg = {"id": pid, "topico": a["topico"], "erro": f"{type(e).__name__}: {str(e)[:200]}"}
        msg["enviado_em"] = datetime.now(timezone.utc).isoformat()
        await socket.send_text(json.dumps(msg, ensure_ascii=False, default=str))

    async def receber() -> None:
        while True:
            msg = json.loads(await socket.receive_text())
            if msg.get("tipo") == "assinar":
                novas = {}
                for item in msg.get("paineis", []):
                    if item.get("topico") in dados.TOPICOS:
                        params = _converter(item["topico"], {k: str(v) for k, v in (item.get("params") or {}).items()})
                        antigo = assinaturas.get(item["id"])
                        mesma = antigo and antigo["topico"] == item["topico"] and antigo["params"] == params
                        novas[item["id"]] = antigo if mesma else {"topico": item["topico"], "params": params, "proximo": 0.0}
                assinaturas.clear()
                assinaturas.update(novas)
            elif msg.get("tipo") == "atualizar" and msg.get("id") in assinaturas:
                a = assinaturas[msg["id"]]
                a["proximo"] = time.time() + dados.TOPICOS[a["topico"]][1]
                asyncio.create_task(enviar(msg["id"], a, forcar=True))

    async def empurrar() -> None:
        while True:
            agora = time.time()
            for pid, a in list(assinaturas.items()):
                if agora >= a["proximo"]:
                    a["proximo"] = agora + dados.TOPICOS[a["topico"]][1]
                    asyncio.create_task(enviar(pid, a))
            await asyncio.sleep(1)

    tarefas = [asyncio.create_task(receber()), asyncio.create_task(empurrar())]
    try:
        await asyncio.wait(tarefas, return_when=asyncio.FIRST_EXCEPTION)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tarefas:
            t.cancel()


# ---------------------------------------------------------------- relatórios (motor de análise)

ARQUIVOS_RELATORIO = {"relatorio.pdf": "application/pdf", "planilha.xlsx":
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "relatorio.md": "text/markdown"}


@app.get("/api/relatorios")
def api_relatorios(busca: str = "", limite: int = 30) -> dict:
    from quiron.servicos.analise.fila import fila

    f = fila()
    tarefas = f.buscar(busca, limite) if busca.strip() else f.listar(limite)
    return {"itens": [{"id": t.id, "titulo": t.titulo or t.tipo, "situacao": t.situacao, "erro": t.erro,
                       "quando": (t.terminada_em or t.criada_em).replace("T", " ")[:16],
                       "pdf": "pdf" in t.arquivos(), "planilha": "planilha" in t.arquivos()} for t in tarefas]}


@app.get("/relatorios/{ident}/{arquivo}")
def baixar_relatorio(ident: int, arquivo: str) -> FileResponse:
    from quiron.servicos.analise.fila import fila

    if arquivo not in ARQUIVOS_RELATORIO:
        raise HTTPException(404)
    t = fila().obter(ident)
    if not t or not t.pasta or not (Path(t.pasta) / arquivo).exists():
        raise HTTPException(404)
    nome = f"quiron-{ident:04d}-{arquivo}"
    return FileResponse(Path(t.pasta) / arquivo, media_type=ARQUIVOS_RELATORIO[arquivo], filename=nome)


# ---------------------------------------------------------------- acervo (upload por área)

HOSTS_LOCAIS = {"127.0.0.1", "localhost"}


def _proteger_acervo(request: Request) -> None:
    """Escrita no acervo: exige o cabeçalho da própria tela (bloqueia outros sites) e, sem senha, só aceita o PC local
    ou o endereço do Tailscale (bloqueia 'DNS rebinding')."""
    if request.headers.get("x-quiron") != "acervo":
        raise HTTPException(403, "pedido fora da tela do Acervo")
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if not _senha() and host not in HOSTS_LOCAIS | {"testserver"} and not host.endswith(".ts.net"):
        raise HTTPException(403, "endereço não permitido sem TERMINAL_SENHA")


def _registro_json(r) -> dict:
    return {"id": r.id, "area": r.area, "nome": r.nome, "tamanho": r.tamanho, "enviado_em": r.enviado_em,
            "situacao": r.situacao, "detalhe": r.detalhe, "pronto": r.situacao in {"pronto", "já estava", "área atualizada"}}


@app.get("/acervo")
def pagina_acervo() -> FileResponse:
    return FileResponse(FRONTEND / "acervo.html")


@app.get("/api/acervo")
def api_acervo() -> dict:
    from quiron.servicos.acervo import FORMATOS, LIMITE_BYTES, acervo

    a = acervo()
    a.iniciar_processador()
    return {"areas": a.resumo_areas(), "arquivos": [_registro_json(r) for r in a.listar(300)],
            "formatos": sorted(FORMATOS), "limite_mb": LIMITE_BYTES // (1024 * 1024)}


@app.put("/api/acervo/arquivo")
async def api_acervo_enviar(request: Request, area: str, nome: str) -> dict:
    from quiron.servicos.acervo import AcervoErro, acervo

    _proteger_acervo(request)
    a = acervo()
    try:
        ident = await a.salvar_em_partes(area, nome, request.stream())
    except AcervoErro as e:
        raise HTTPException(400, str(e)) from e
    a.iniciar_processador()
    return _registro_json(a.obter(ident))


@app.post("/api/acervo/area")
async def api_acervo_nova_area(request: Request, corpo: dict = Body(...)) -> dict:
    from quiron.servicos import areas

    _proteger_acervo(request)
    try:
        nova = areas.criar(str(corpo.get("nome", "")), str(corpo.get("descricao", "")), str(corpo.get("tipo", "campo")))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"id": nova.id, "nome": nova.nome, "tipo": nova.tipo}


@app.post("/api/acervo/mover")
async def api_acervo_mover(request: Request, corpo: dict = Body(...)) -> dict:
    from quiron.servicos.acervo import AcervoErro, acervo

    _proteger_acervo(request)
    try:
        return _registro_json(acervo().mover(int(corpo.get("id", 0)), str(corpo.get("area", ""))))
    except (AcervoErro, ValueError) as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/acervo/arquivo/{ident}")
async def api_acervo_remover(request: Request, ident: int) -> dict:
    from quiron.servicos.acervo import AcervoErro, acervo

    _proteger_acervo(request)
    try:
        acervo().remover(ident)
    except AcervoErro as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


# ---------------------------------------------------------------- páginas

@app.get("/")
def inicio() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")


def main() -> None:
    """`uv run quiron-terminal` — abre o Terminal no navegador."""
    import argparse
    import threading
    import webbrowser

    import uvicorn

    p = argparse.ArgumentParser(description="Quíron Terminal")
    p.add_argument("--porta", type=int, default=int(os.environ.get("TERMINAL_PORTA", "8765").split(" #")[0] or 8765))
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = só este PC (padrão)")
    p.add_argument("--sem-navegador", action="store_true")
    p.add_argument("--abrir", default="", help="página a abrir no navegador (ex.: /acervo)")
    a = p.parse_args()
    url = f"http://{'localhost' if a.host in {'127.0.0.1', '0.0.0.0'} else a.host}:{a.porta}"
    from quiron.servicos.acervo import acervo

    acervo().iniciar_processador()  # processa a fila do acervo em segundo plano
    print(f"Quíron Terminal em {url}  (feche esta janela para desligar)")
    if not a.sem_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url + a.abrir)).start()
    uvicorn.run(app, host=a.host, port=a.porta, log_level="warning")


if __name__ == "__main__":
    main()
