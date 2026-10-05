"""Tela de Configurações do Quíron: preenche e testa as chaves do `.env` sem abrir o Bloco de Notas.

- Só escuta em 127.0.0.1 e exige um código aleatório gerado a cada abertura (outro site aberto no navegador
  não consegue ler nem gravar as chaves).
- As chaves nunca voltam inteiras para a página: só "preenchida, termina em …".
- O `.env` é atualizado no lugar (comentários e outras linhas são mantidos); se não existir, nasce do `.env.example`.
- `quiron-configurar --verificar` sai com código 0 se o essencial estiver preenchido (usado pelo `Abrir Quiron.bat`).
"""

from __future__ import annotations

import argparse
import re
import secrets
import threading
import webbrowser
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from quiron.nucleo.config import RAIZ

PAGINA = Path(__file__).with_name("pagina.html")
PORTA_PADRAO = 8766

# chave, rótulo, grupo, obrigatória, segredo, ajuda
CAMPOS: list[dict[str, Any]] = [
    {"chave": "TELEGRAM_BOT_TOKEN", "rotulo": "Token do bot", "grupo": "Telegram", "obrigatorio": True, "segredo": True,
     "ajuda": "No Telegram, fale com @BotFather → /mybots → seu bot → API Token.", "teste": True},
    {"chave": "TELEGRAM_ALLOWED_USER_IDS", "rotulo": "Seu ID (quem pode falar com o Quíron)", "grupo": "Telegram",
     "obrigatorio": True, "segredo": False, "ajuda": "É um NÚMERO, não o @usuário. Use o botão “Descobrir meu ID”.",
     "teste": False},
    {"chave": "GEMINI_API_KEY", "rotulo": "Chave do Gemini (cérebro principal)", "grupo": "Cérebro (IA)",
     "obrigatorio": True, "segredo": True, "ajuda": "Grátis em aistudio.google.com → Get API key.", "teste": True},
    {"chave": "GROQ_API_KEY", "rotulo": "Chave do Groq (reserva e áudio)", "grupo": "Cérebro (IA)",
     "obrigatorio": False, "segredo": True, "ajuda": "Grátis em console.groq.com → API Keys. Recomendado: sem ela não há áudio.",
     "teste": True},
    {"chave": "BRAPI_TOKEN", "rotulo": "Token da brapi (cotações)", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": True, "ajuda": "Grátis em brapi.dev. Sem ele, as cotações vêm do Yahoo.", "teste": True},
    {"chave": "TERMINAL_SENHA", "rotulo": "Senha do Terminal", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": True, "ajuda": "Só necessária no servidor (mini PC/VPS). No seu PC pode ficar vazia.", "teste": False},
    {"chave": "GOOGLE_AGENDA_ID", "rotulo": "Agenda do Google a usar", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": False, "ajuda": "Vazio = sua agenda principal. Outra agenda: Configurações da agenda → “ID da agenda”.",
     "teste": False},
    {"chave": "YOUTUBE_API_KEY", "rotulo": "Chave do YouTube", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": True, "ajuda": "console.cloud.google.com → YouTube Data API v3.", "teste": False},
    {"chave": "BLUESKY_HANDLE", "rotulo": "Usuário do Bluesky", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": False, "ajuda": "Ex.: voce.bsky.social", "teste": False},
    {"chave": "BLUESKY_APP_PASSWORD", "rotulo": "Senha de app do Bluesky", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": True, "ajuda": "Bluesky → Configurações → Senhas de app.", "teste": False},
    {"chave": "REDDIT_CLIENT_ID", "rotulo": "Reddit: client id", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": False, "ajuda": "reddit.com/prefs/apps → app do tipo script.", "teste": False},
    {"chave": "REDDIT_CLIENT_SECRET", "rotulo": "Reddit: secret", "grupo": "Opcionais", "obrigatorio": False,
     "segredo": True, "ajuda": "Mesmo app do Reddit.", "teste": False},
]
POR_CHAVE = {c["chave"]: c for c in CAMPOS}
RE_LINHA = re.compile(r"^(\s*)([A-Z][A-Z0-9_]*)=(.*)$")


# ---------------------------------------------------------------- arquivo .env
def caminho_env() -> Path:
    return RAIZ / ".env"


def _limpo(valor: str | None) -> str:
    return (valor or "").split(" #")[0].strip().strip('"').strip("'")


def ler_valores(caminho: Path | None = None) -> dict[str, str]:
    caminho = caminho or caminho_env()
    if not caminho.exists():
        return {}
    return {k: _limpo(v) for k, v in dotenv_values(caminho).items() if k}


def ids_validos(texto: str) -> bool:
    itens = [x.strip() for x in texto.replace(";", ",").split(",") if x.strip()]
    return bool(itens) and all(x.isdigit() for x in itens)


def faltando(valores: dict[str, str]) -> list[str]:
    """Campos obrigatórios vazios ou inválidos."""
    falta = [c["chave"] for c in CAMPOS if c["obrigatorio"] and not valores.get(c["chave"])]
    ids = valores.get("TELEGRAM_ALLOWED_USER_IDS", "")
    if ids and not ids_validos(ids):
        falta.append("TELEGRAM_ALLOWED_USER_IDS")
    return falta


def atualizar_env(valores: dict[str, str], caminho: Path | None = None) -> None:
    """Grava as chaves no .env mantendo comentários, ordem e as demais linhas."""
    caminho = caminho or caminho_env()
    for k, v in valores.items():
        if "\n" in v or "\r" in v:
            raise ValueError(f"{k}: valor com quebra de linha")
    if caminho.exists():
        texto = caminho.read_text(encoding="utf-8")
    elif (modelo := caminho.with_name(".env.example")).exists():
        texto = modelo.read_text(encoding="utf-8")
    else:
        texto = ""
    pendentes = dict(valores)
    linhas = []
    for linha in texto.splitlines():
        m = RE_LINHA.match(linha)
        if m and m.group(2) in pendentes:
            resto = m.group(3)
            i = resto.find(" #")
            comentario = resto[i:].strip() if i >= 0 else ""
            nova = f"{m.group(1)}{m.group(2)}={pendentes.pop(m.group(2))}"
            linha = f"{nova:<40} {comentario}" if comentario else nova
        linhas.append(linha)
    linhas += [f"{k}={v}" for k, v in pendentes.items()]
    temp = caminho.with_suffix(".tmp")
    temp.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    temp.replace(caminho)


def mascara(valor: str) -> str:
    return f"preenchida · termina em …{valor[-4:]}" if len(valor) > 8 else ("preenchida" if valor else "")


def estado(caminho: Path | None = None) -> dict[str, Any]:
    valores = ler_valores(caminho)
    falta = faltando(valores)
    campos = []
    for c in CAMPOS:
        v = valores.get(c["chave"], "")
        campos.append({**c, "preenchido": bool(v), "invalido": c["chave"] in falta and bool(v),
                       "mascara": mascara(v) if c["segredo"] else "", "valor": "" if c["segredo"] else v})
    return {"campos": campos, "faltando": falta, "completo": not falta, "arquivo": str(caminho or caminho_env())}


def salvar_valores(valores: dict[str, Any]) -> dict[str, str]:
    """Valida e grava o que veio da tela; segredo em branco = manter o atual. Devolve o que foi gravado."""
    novos = {k: str(v).strip() for k, v in (valores or {}).items() if k in POR_CHAVE}
    novos = {k: v for k, v in novos.items() if v or not POR_CHAVE[k]["segredo"]}
    ids = novos.get("TELEGRAM_ALLOWED_USER_IDS")
    if ids:
        ids = ",".join(x.strip() for x in ids.replace(";", ",").split(",") if x.strip())
        if not ids_validos(ids):
            raise ValueError("O ID precisa ser só números (ex.: 7592218870), não o @usuário.")
        novos["TELEGRAM_ALLOWED_USER_IDS"] = ids
    atualizar_env(novos)
    return novos


# ---------------------------------------------------------------- testes de conexão
def _cliente() -> httpx.Client:
    return httpx.Client(timeout=15)


def testar(chave: str, valor: str) -> dict[str, Any]:
    if not valor:
        return {"ok": False, "mensagem": "Preencha antes de testar."}
    try:
        with _cliente() as c:
            if chave == "TELEGRAM_BOT_TOKEN":
                r = c.get(f"https://api.telegram.org/bot{valor}/getMe")
                if r.status_code == 200 and r.json().get("ok"):
                    u = r.json()["result"]
                    return {"ok": True, "mensagem": f"Bot encontrado: @{u.get('username')} ({u.get('first_name')})",
                            "bot": u.get("username")}
                return {"ok": False, "mensagem": "Token recusado pelo Telegram. Copie de novo no @BotFather."}
            if chave == "GEMINI_API_KEY":
                r = c.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": valor})
                return {"ok": True, "mensagem": "Gemini respondeu: chave válida."} if r.status_code == 200 else \
                    {"ok": False, "mensagem": f"Gemini recusou a chave (erro {r.status_code})."}
            if chave == "GROQ_API_KEY":
                r = c.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {valor}"})
                return {"ok": True, "mensagem": "Groq respondeu: chave válida."} if r.status_code == 200 else \
                    {"ok": False, "mensagem": f"Groq recusou a chave (erro {r.status_code})."}
            if chave == "BRAPI_TOKEN":
                r = c.get("https://brapi.dev/api/quote/PETR4", params={"token": valor})
                return {"ok": True, "mensagem": "brapi respondeu: token válido."} if r.status_code == 200 else \
                    {"ok": False, "mensagem": f"brapi recusou o token (erro {r.status_code})."}
    except httpx.HTTPError as e:
        return {"ok": False, "mensagem": f"Sem conexão com o serviço ({type(e).__name__}). Confira a internet."}
    return {"ok": False, "mensagem": "Este campo não tem teste."}


def descobrir_ids(token: str) -> dict[str, Any]:
    """Lê as últimas mensagens recebidas pelo bot e devolve quem escreveu (para escolher o próprio ID)."""
    if not token:
        return {"ok": False, "mensagem": "Preencha e salve o token do bot primeiro."}
    try:
        with _cliente() as c:
            r = c.get(f"https://api.telegram.org/bot{token}/getUpdates", params={"limit": 50})
    except httpx.HTTPError as e:
        return {"ok": False, "mensagem": f"Sem conexão com o Telegram ({type(e).__name__})."}
    if r.status_code == 409:
        return {"ok": False, "mensagem": "O Quíron está ligado em outro lugar e já leu as mensagens. "
                                         "Feche a janela do Quíron, mande /start de novo e tente outra vez."}
    if r.status_code != 200:
        return {"ok": False, "mensagem": "Token recusado pelo Telegram."}
    pessoas: dict[int, dict[str, Any]] = {}
    for u in r.json().get("result", []):
        msg = u.get("message") or u.get("edited_message") or (u.get("callback_query") or {})
        de = msg.get("from") or {}
        if de.get("id") and not de.get("is_bot"):
            pessoas[de["id"]] = {"id": de["id"], "nome": " ".join(filter(None, [de.get("first_name"), de.get("last_name")])),
                                 "usuario": de.get("username") or ""}
    if not pessoas:
        return {"ok": False, "mensagem": "Nenhuma mensagem encontrada. Abra o seu bot no Telegram, mande /start "
                                         "e clique de novo."}
    return {"ok": True, "pessoas": list(pessoas.values())}


# ---------------------------------------------------------------- servidor
def criar_app(codigo: str, porta: int, ao_concluir=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    hosts = {f"127.0.0.1:{porta}", f"localhost:{porta}", "testserver"}

    @app.middleware("http")
    async def proteger(request: Request, call_next):
        if request.headers.get("host") not in hosts:  # bloqueia "DNS rebinding"
            return JSONResponse({"erro": "host"}, status_code=403)
        if request.url.path.startswith("/api/") and not secrets.compare_digest(
                request.headers.get("x-quiron-codigo", ""), codigo):
            return JSONResponse({"erro": "código inválido — abra pelo atalho do Quíron"}, status_code=403)
        resposta = await call_next(request)
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["X-Frame-Options"] = "DENY"
        return resposta

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return PAGINA.read_text(encoding="utf-8")

    @app.get("/api/estado")
    def api_estado() -> dict[str, Any]:
        return estado()

    @app.post("/api/salvar")
    async def api_salvar(request: Request) -> dict[str, Any]:
        corpo = await request.json()
        try:
            salvar_valores(corpo.get("valores") or {})
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return estado()

    @app.post("/api/apagar")
    async def api_apagar(request: Request) -> dict[str, Any]:
        chave = (await request.json()).get("chave")
        if chave not in POR_CHAVE:
            raise HTTPException(400, "campo desconhecido")
        atualizar_env({chave: ""})
        return estado()

    @app.post("/api/testar")
    async def api_testar(request: Request) -> dict[str, Any]:
        corpo = await request.json()
        chave = corpo.get("chave", "")
        valor = str(corpo.get("valor") or "").strip() or ler_valores().get(chave, "")
        return testar(chave, valor)

    @app.post("/api/descobrir_id")
    async def api_descobrir(request: Request) -> dict[str, Any]:
        corpo = await request.json()
        token = str(corpo.get("token") or "").strip() or ler_valores().get("TELEGRAM_BOT_TOKEN", "")
        return descobrir_ids(token)

    @app.post("/api/concluir")
    def api_concluir() -> dict[str, Any]:
        e = estado()
        if e["completo"] and ao_concluir:
            threading.Timer(0.5, ao_concluir).start()
        return e

    return app


def main() -> None:
    """`uv run quiron-configurar` abre a tela no navegador; `--verificar` só confere se o essencial está preenchido."""
    import uvicorn

    p = argparse.ArgumentParser(description="Configurações do Quíron")
    p.add_argument("--verificar", action="store_true", help="sai com 0 se o essencial estiver preenchido, 1 se não")
    p.add_argument("--porta", type=int, default=PORTA_PADRAO)
    p.add_argument("--sem-navegador", action="store_true")
    a = p.parse_args()
    if a.verificar:
        falta = faltando(ler_valores())
        if falta:
            print("Falta configurar:", ", ".join(POR_CHAVE[k]["rotulo"] for k in falta))
        raise SystemExit(1 if falta else 0)

    codigo = secrets.token_urlsafe(24)
    servidor: uvicorn.Server | None = None

    def parar() -> None:
        if servidor:
            servidor.should_exit = True

    app = criar_app(codigo, a.porta, ao_concluir=parar)
    endereco = f"http://127.0.0.1:{a.porta}/#{codigo}"  # o código vai no "#": não sai do navegador nem fica em logs
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=a.porta, log_level="warning"))
    print(f"Configurações do Quíron abertas no navegador. Se não abrir, acesse:\n  {endereco}\n"
          "Clique em “Salvar e concluir” quando terminar (ou feche esta janela para sair).")
    if not a.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(endereco)).start()
    servidor.run()
