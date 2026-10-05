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
import re
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
    livre = request.url.path in {"/login", "/app.css", "/manifest.webmanifest", "/icone.svg"} or request.url.path.startswith("/vendor/")
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


# ---------------------------------------------------------------- Terminal v2 (Fase 12): ações
def _proteger(request: Request) -> None:
    """Toda ação que grava ou dispara algo exige o cabeçalho da própria tela (bloqueia outros sites)."""
    if request.headers.get("x-quiron") not in {"terminal", "acervo"}:
        raise HTTPException(403, "pedido fora da tela do Terminal")
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if not _senha() and host not in HOSTS_LOCAIS | {"testserver"} and not host.endswith(".ts.net"):
        raise HTTPException(403, "endereço não permitido sem TERMINAL_SENHA")


def _iniciar_fila() -> None:
    """O Terminal também processa a fila de análises (vários processadores convivem: a reserva é atômica)."""
    try:
        from quiron.servicos.analise.fila import fila

        fila().iniciar_processador()
    except Exception:  # noqa: BLE001
        pass


@app.post("/api/analisar")
def api_analisar(request: Request, corpo: dict = Body(...)) -> dict:
    from quiron.servicos.analise.fila import carregar_tipos, fila

    _proteger(request)
    tipo_nome = str(corpo.get("tipo", ""))
    if tipo_nome not in carregar_tipos():
        raise HTTPException(400, f"tipo de análise desconhecido: {tipo_nome}")
    f = fila()
    t = f.pedir(tipo_nome, corpo.get("parametros") or {}, str(corpo.get("modo") or "entregar"), origem="terminal")
    f.iniciar_processador()
    return {"id": t.id, "situacao": t.situacao, "na_frente": f.posicao(t.id)}


@app.post("/api/carteira/ler")
def api_carteira_ler(request: Request, corpo: dict = Body(...)) -> dict:
    """PORT: lê a carteira colada (texto), guarda (CART-…) e devolve composição e enquadramento no perfil."""
    from quiron.servicos.analise.tipos.carteira import _enquadramento
    from quiron.servicos.carteira import arquivo, leitura
    from quiron.servicos.carteira.modelo import CLASSES, perfis

    _proteger(request)
    texto = str(corpo.get("texto", "")).strip()
    if len(texto) < 3:
        raise HTTPException(400, "cole a carteira (uma posição por linha)")
    c = leitura.avaliar(leitura.ler_texto(texto))
    if corpo.get("perfil"):
        c.perfil = str(corpo["perfil"]).lower()
    if corpo.get("cliente"):
        c.cliente = str(corpo["cliente"]).upper() if str(corpo["cliente"]).upper().startswith("CLI-") else ""
    if not c.posicoes:
        raise HTTPException(400, "não achei posições com valor")
    ident = arquivo.salvar(c)
    perfil = c.perfil if c.perfil in perfis() else "moderado"
    pesos = c.pesos_por_classe()
    return {"id": ident, "total": c.total, "perfil": perfil, "avisos": c.avisos,
            "posicoes": [{"nome": p.nome, "classe": CLASSES[p.classe]["nome"], "valor": p.valor} for p in c.posicoes],
            "enquadramento": [dict(zip(["classe", "atual", "minimo", "alvo", "maximo", "situacao"], linha))
                              for linha in _enquadramento(pesos, perfis()[perfil]["classes"])]}


@app.post("/api/simulador")
def api_simulador(request: Request, corpo: dict = Body(...)) -> dict:
    """SIM — simulador de patrimônio (só calcula, nada é gravado). `cliente` (CLI-XXX) usa a ficha de planejamento."""
    from quiron.servicos.planejamento import simulador

    _proteger(request)
    dados = {k: v for k, v in (corpo or {}).items() if k != "cliente"}
    cliente = str((corpo or {}).get("cliente") or "").strip().upper()
    try:
        if cliente:
            if not re.fullmatch(r"CLI-\w+", cliente):
                raise ValueError("cliente só como código CLI-XXX")
            e = simulador.de_ficha(cliente, **{k: v for k, v in dados.items() if k not in {"idade", "perfil"}})
        else:
            e = simulador.Entrada.de_dict(dados)
        sim = simulador.simular(e)
    except (ValueError, TypeError) as erro:
        raise HTTPException(400, str(erro)) from erro
    return {**sim.como_dict(), "texto": simulador.texto(sim)}


@app.post("/api/alertas")
def api_alerta_criar(request: Request, corpo: dict = Body(...)) -> dict:
    from quiron.servicos import alertas

    _proteger(request)
    try:
        valor = corpo.get("valor")
        a = alertas.criar(str(corpo.get("tipo", "")), str(corpo.get("alvo", "")),
                          float(str(valor).replace(",", ".")) if valor not in (None, "") else None)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
    return {"id": a.id, "descricao": a.descrever()}


@app.post("/api/alertas/avaliar")
def api_alertas_avaliar(request: Request) -> dict:
    from quiron.servicos import alertas

    _proteger(request)
    return {"disparados": [a.descrever() for a in alertas.avaliar()]}


@app.delete("/api/alertas/{ident}")
def api_alerta_remover(request: Request, ident: int) -> dict:
    from quiron.servicos import alertas

    _proteger(request)
    return {"ok": alertas.remover(ident)}


@app.post("/api/tarefas")
def api_tarefa_criar(request: Request, corpo: dict = Body(...)) -> dict:
    from quiron.runtime.agendador import BRT, Agendador, RecorrenciaInvalida

    _proteger(request)
    quando = None
    if corpo.get("quando"):
        try:
            quando = datetime.fromisoformat(str(corpo["quando"])).replace(tzinfo=BRT)
        except ValueError as e:
            raise HTTPException(400, "data/hora inválida") from e
    try:
        a = Agendador().criar(str(corpo.get("texto", "")).strip() or "(sem texto)", str(corpo.get("tipo") or "lembrete"),
                              str(corpo.get("recorrencia") or "uma vez"), quando)
    except (RecorrenciaInvalida, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {"id": a.id, "descricao": a.descrever()}


@app.post("/api/organizacao/tarefa")
def api_org_tarefa(request: Request, corpo: dict = Body(...)) -> dict:
    """Tarefa rápida em linguagem natural ("amanhã às 10h ligar para o CLI-012")."""
    from quiron.servicos.organizacao import tarefas as org

    _proteger(request)
    try:
        t = org.criar(str(corpo.get("texto", "")), origem="terminal")
    except org.TarefaInvalida as e:
        raise HTTPException(400, str(e)) from e
    return {"id": t.id, "descricao": org.confirmar(t)}


@app.post("/api/organizacao/tarefa/{ident}/{acao}")
def api_org_acao(request: Request, ident: int, acao: str) -> dict:
    from quiron.servicos.organizacao import tarefas as org

    _proteger(request)
    try:
        if acao == "feito":
            return {"descricao": "✅ " + org.concluir(ident).texto}
        if acao == "apagar":
            return {"ok": org.remover(ident)}
        if acao == "amanha":
            return {"descricao": org.confirmar(org.adiar(ident, "amanhã"))}
    except org.TarefaInvalida as e:
        raise HTTPException(400, str(e)) from e
    raise HTTPException(404, "ação desconhecida")


@app.delete("/api/tarefas/{ident}")
def api_tarefa_remover(request: Request, ident: int) -> dict:
    from quiron.runtime.agendador import Agendador

    _proteger(request)
    return {"ok": Agendador().cancelar(ident)}


# ---------------------------------------------------------------- versão offline (Fase 16): biblioteca e cofre
@app.get("/api/modo")
def api_modo() -> dict:
    from quiron.nucleo import offline
    from quiron.servicos.offline import cofre

    return {"offline": offline.ativo(), "modelo": offline.modelo() if offline.ativo() else "",
            "cofre_existe": offline.ativo() and cofre.existe(), "cofre_aberto": _cofre.aberto()}


@app.get("/api/biblioteca")
def api_biblioteca(q: str = "", n: int = 6) -> dict:
    """BIB: trechos da biblioteca com citação (funciona sem internet — o índice é local)."""
    from quiron.servicos.biblioteca import consultas

    if len(q.strip()) < 2:
        raise HTTPException(400, "digite o que procurar")
    return {"texto": consultas.buscar(q.strip(), max(1, min(n, 12)))}


class _CofreSessao:
    """Cofre aberto na memória do Terminal local; fecha sozinho após 15 minutos sem uso."""

    MINUTOS = 15

    def __init__(self) -> None:
        self.cofre = None
        self.ultimo = 0.0

    def aberto(self) -> bool:
        import time as _t

        if self.cofre is not None and _t.time() - self.ultimo > self.MINUTOS * 60:
            self.cofre = None
        return self.cofre is not None

    def obter(self):
        import time as _t

        if not self.aberto():
            raise HTTPException(423, "cofre fechado — digite a senha")
        self.ultimo = _t.time()
        return self.cofre


_cofre = _CofreSessao()


def _so_offline_local(request: Request) -> None:
    """Cofre: só na versão offline e só no próprio PC (nunca pelo Tailscale ou outro endereço)."""
    from quiron.nucleo import offline

    _proteger(request)
    if not offline.ativo():
        raise HTTPException(403, "o cofre só existe na versão offline")
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    cliente = request.client.host if request.client else ""
    if host not in HOSTS_LOCAIS | {"testserver"} or cliente not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "o cofre só abre no próprio PC")


@app.post("/api/cofre/abrir")
def api_cofre_abrir(request: Request, corpo: dict = Body(...)) -> dict:
    import time as _t

    from quiron.servicos.offline import cofre

    _so_offline_local(request)
    senha = str(corpo.get("senha", ""))
    try:
        _cofre.cofre = cofre.abrir(senha) if cofre.existe() or not corpo.get("criar") else cofre.criar(senha)
    except (cofre.SenhaErrada, cofre.CofreBloqueado, FileNotFoundError, FileExistsError, ValueError) as e:
        raise HTTPException(401 if isinstance(e, cofre.SenhaErrada) else 400, str(e)) from e
    _cofre.ultimo = _t.time()
    return {"ok": True, "clientes": len(_cofre.cofre.clientes)}


@app.post("/api/cofre/fechar")
def api_cofre_fechar(request: Request) -> dict:
    _so_offline_local(request)
    _cofre.cofre = None
    return {"ok": True}


@app.get("/api/cofre/clientes")
def api_cofre_clientes(request: Request, q: str = "") -> dict:
    from dataclasses import asdict

    _so_offline_local(request)
    c = _cofre.obter()
    itens = c.buscar(q) if q.strip() else sorted(c.clientes.values(), key=lambda x: x.nome)
    return {"itens": [asdict(x) for x in itens]}


@app.get("/api/cofre/cliente/{codigo}")
def api_cofre_cliente(request: Request, codigo: str) -> dict:
    """Cliente real: dados do cofre + dossiê (ficha, carteira, vencimentos, reuniões, tarefas) pelo código."""
    from dataclasses import asdict

    from quiron.servicos.assessoria import dossie
    from quiron.servicos.planejamento.ficha import codigo as normalizar

    _so_offline_local(request)
    c = _cofre.obter()
    try:
        cod = normalizar(codigo)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if cod not in c.clientes:
        raise HTTPException(404, f"{cod} não está no cofre")
    return {"cliente": asdict(c.clientes[cod]), "dossie": dossie.montar(cod)}


@app.post("/api/cofre/cliente")
def api_cofre_gravar(request: Request, corpo: dict = Body(...)) -> dict:
    from dataclasses import asdict

    _so_offline_local(request)
    c = _cofre.obter()
    try:
        x = c.gravar(str(corpo.get("codigo", "")), **{k: corpo.get(k) for k in ("nome", "cpf", "telefone", "email", "cidade", "observacoes")})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"cliente": asdict(x)}


@app.delete("/api/cofre/cliente/{codigo}")
def api_cofre_remover(request: Request, codigo: str) -> dict:
    _so_offline_local(request)
    return {"ok": _cofre.obter().remover(codigo)}


@app.get("/api/offline/pacote")
def api_offline_pacote(request: Request) -> FileResponse:
    """Pacote de dados para o PC offline (índice da biblioteca, fichas, Academia…). Só com TERMINAL_SENHA configurada."""
    from quiron.servicos.offline import pacote

    _proteger(request)
    if not _senha():
        raise HTTPException(403, "configure a TERMINAL_SENHA no servidor para liberar o pacote offline")
    arq = pacote.gerar()
    return FileResponse(arq, media_type="application/gzip", filename=arq.name)


# ---------------------------------------------------------------- chat com o agente (Fase 12.3)
CHAT_TERMINAL = -12  # conversa do Terminal na memória do agente (o Telegram usa o id do chat)


class _Chat:
    """Agente do Quíron dentro do Terminal: sobe os servidores MCP na primeira mensagem e os mantém ligados."""

    def __init__(self) -> None:
        self.agente = None
        self._pilha = None
        self._trava = asyncio.Lock()

    async def obter(self):
        async with self._trava:
            if self.agente is None:
                from contextlib import AsyncExitStack

                from quiron.runtime.agente import Agente
                from quiron.runtime.ferramentas_mcp import ConexaoMCP

                os.environ.setdefault("QUIRON_ORIGEM", "terminal")
                self._pilha = AsyncExitStack()
                conexao = await self._pilha.enter_async_context(ConexaoMCP())
                self.agente = Agente(conexao)
            return self.agente


_chat = _Chat()


def _pendencias(reg) -> list[dict]:
    return [{"id": p.id, "resumo": p.resumo} for p in reg.pendencias]


@app.post("/api/chat")
async def api_chat(request: Request, corpo: dict = Body(...)) -> dict:
    _proteger(request)
    texto = str(corpo.get("texto", "")).strip()
    if not texto:
        raise HTTPException(400, "mensagem vazia")
    try:
        agente = await _chat.obter()
        if texto == "/novo":
            agente.memoria.reiniciar(CHAT_TERMINAL)
            return {"resposta": "Conversa reiniciada.", "pendencias": [], "ferramentas": []}
        reg = await agente.responder(texto, chat=CHAT_TERMINAL)
    except Exception as e:  # noqa: BLE001
        return {"resposta": f"⚠️ O agente não respondeu ({type(e).__name__}: {str(e)[:200]}).", "pendencias": [], "ferramentas": []}
    return {"resposta": reg.resposta or "(sem resposta)", "pendencias": _pendencias(reg), "ferramentas": reg.ferramentas,
            "segundos": round(reg.segundos, 1)}


@app.get("/api/chat/historico")
async def api_chat_historico() -> dict:
    from quiron.runtime.memoria import Memoria

    return {"mensagens": [{"papel": m["role"], "texto": m["content"]} for m in Memoria().historico(CHAT_TERMINAL)
                          if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)][-30:]}


@app.post("/api/chat/decidir")
async def api_chat_decidir(request: Request, corpo: dict = Body(...)) -> dict:
    _proteger(request)
    agente = await _chat.obter()
    p = agente.aprovacoes.decidir(int(corpo.get("id", 0)), bool(corpo.get("aprovar")))
    if not p:
        return {"resposta": "Esse pedido já foi decidido ou não existe."}
    if not corpo.get("aprovar"):
        return {"resposta": f"❌ Negado: {p.resumo}"}
    return {"resposta": f"✅ Aprovado e feito: {p.resumo}\n{(await agente.executar_aprovada(p))[:3000]}"}


# ---------------------------------------------------------------- central (aba CONFIGURAÇÕES)
from quiron.terminal.backend import central  # noqa: E402

app.include_router(central.router)


# ---------------------------------------------------------------- páginas

@app.get("/")
def inicio() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/config")
def pagina_config() -> FileResponse:
    return FileResponse(FRONTEND / "config.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")


def main(argv: list[str] | None = None) -> int:
    """`uv run quiron-terminal` — abre o Terminal no navegador.

    Com `--central` (o lançador `quiron` usa) o Terminal também cuida do bot do Telegram e da troca de modo."""
    import argparse
    import sys
    import threading
    import webbrowser

    import uvicorn

    from quiron.configurador import app as configurador

    p = argparse.ArgumentParser(description="Quíron Terminal")
    p.add_argument("--porta", type=int, default=int(os.environ.get("TERMINAL_PORTA", "8765").split(" #")[0] or 8765))
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = só este PC (padrão)")
    p.add_argument("--sem-navegador", action="store_true")
    p.add_argument("--abrir", default="", help="página a abrir no navegador (ex.: /acervo)")
    p.add_argument("--central", action="store_true", help="também liga e supervisiona o bot do Telegram")
    a = p.parse_args(argv)
    url = f"http://{'localhost' if a.host in {'127.0.0.1', '0.0.0.0'} else a.host}:{a.porta}"
    from quiron.servicos.acervo import acervo

    carregar_config()
    acervo().iniciar_processador()  # processa a fila do acervo em segundo plano
    completo = not configurador.faltando(configurador.ler_valores())
    abrir = a.abrir or ("" if completo else "/config")  # primeira vez: direto para as chaves
    servidor = uvicorn.Server(uvicorn.Config(app, host=a.host, port=a.porta, log_level="warning"))
    codigo = {"saida": 0}
    if a.central:
        from quiron.nucleo import offline

        central.SUPERVISOR.gerenciado = True

        def sair(c: int) -> None:
            codigo["saida"] = c
            servidor.should_exit = True

            def forcar() -> None:  # consultas lentas em andamento (rede) não seguram a troca de modo
                central.SUPERVISOR.desligar()
                os._exit(c)

            relogio = threading.Timer(5, forcar)
            relogio.daemon = True
            relogio.start()

        central.SAIR = sair
        threading.Thread(target=central.copia_diaria_da_memoria, name="copia-memoria", daemon=True).start()
        if completo and not offline.ativo():
            try:
                central.SUPERVISOR.ligar()
                print("Telegram: ligado (registro em dados/logs/telegram.log).")
            except ValueError as e:
                print(f"Telegram: não liguei — {e}")
    print(f"Quíron em {url}  (feche esta janela para desligar tudo)")
    if not a.sem_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url + abrir)).start()
    _iniciar_fila()
    try:
        servidor.run()
    finally:
        central.SUPERVISOR.desligar()
    if codigo["saida"]:
        sys.exit(codigo["saida"])
    return 0

if __name__ == "__main__":
    main()
