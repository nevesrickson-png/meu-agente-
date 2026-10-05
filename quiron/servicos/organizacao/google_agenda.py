"""Google Agenda pela API oficial (Calendar v3), gratuita, com autorização OAuth do próprio Rickson.

- Credencial do app: `segredos/google_oauth.json` (baixada do Google Cloud, tipo "App para computador").
- Autorização: `quiron-google autorizar` abre o navegador; o Rickson entra na conta e permite. Volta para um endereço
  local (127.0.0.1) que só existe durante a autorização (fluxo "loopback" + PKCE, o recomendado pelo Google para apps
  de computador). O token fica em `segredos/google_token.json` (fora do git; renovado sozinho).
- Sem navegador (servidor): `quiron-google autorizar --sem-navegador` mostra o link; depois de permitir, cole aqui o
  endereço da página que não abriu (começa com http://127.0.0.1).
- Escopo: só eventos da agenda (`calendar.events`). Nos eventos, cliente só como CLI-XXX.
Sem bibliotecas extras: httpx.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from quiron.nucleo.config import RAIZ

ESCOPO = "https://www.googleapis.com/auth/calendar.events"
URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"


class AgendaIndisponivel(RuntimeError):
    pass


def _segredos() -> Path:
    return Path(os.environ.get("QUIRON_SEGREDOS") or RAIZ / "segredos")


def arquivo_cliente() -> Path:
    return _segredos() / "google_oauth.json"


def arquivo_token() -> Path:
    return _segredos() / "google_token.json"


def agenda_id() -> str:
    return os.environ.get("GOOGLE_AGENDA_ID", "").split(" #")[0].strip() or "primary"


def configurado() -> bool:
    return arquivo_cliente().exists() and arquivo_token().exists()


def como_configurar() -> str:
    if not arquivo_cliente().exists():
        return ("Google Agenda ainda não configurado: falta a credencial segredos/google_oauth.json. "
                "Siga o passo a passo em docs/09-GOOGLE-AGENDA.md (uns 10 minutos, uma vez só).")
    return "Google Agenda: falta autorizar. No PC, dê dois cliques em “Quiron Google Agenda.bat” (ou rode `uv run quiron-google autorizar`)."


def _cliente_oauth() -> dict[str, str]:
    try:
        bruto = json.loads(arquivo_cliente().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise AgendaIndisponivel(como_configurar()) from e
    dados = bruto.get("installed") or bruto.get("web") or bruto
    if not dados.get("client_id"):
        raise AgendaIndisponivel("segredos/google_oauth.json não parece a credencial do Google (falta client_id).")
    return {"client_id": dados["client_id"], "client_secret": dados.get("client_secret", "")}


# ---------------------------------------------------------------- autorização (uma vez)
def _pkce() -> tuple[str, str]:
    verificador = secrets.token_urlsafe(64)[:96]
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return verificador, desafio


def link_autorizacao(porta: int, estado: str, desafio: str) -> str:
    c = _cliente_oauth()
    return URL_AUTORIZAR + "?" + urlencode({
        "client_id": c["client_id"], "redirect_uri": f"http://127.0.0.1:{porta}/", "response_type": "code", "scope": ESCOPO,
        "access_type": "offline", "prompt": "consent", "state": estado, "code_challenge": desafio, "code_challenge_method": "S256"})


def trocar_codigo(codigo: str, porta: int, verificador: str, cliente_http: httpx.Client | None = None) -> dict[str, Any]:
    c = _cliente_oauth()
    http = cliente_http or httpx.Client(timeout=30)
    r = http.post(URL_TOKEN, data={"code": codigo, "client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "redirect_uri": f"http://127.0.0.1:{porta}/", "grant_type": "authorization_code",
                                   "code_verifier": verificador})
    if r.status_code != 200:
        raise AgendaIndisponivel(f"O Google recusou a autorização ({r.status_code}): {r.text[:200]}")
    token = r.json()
    if not token.get("refresh_token"):
        raise AgendaIndisponivel("O Google não devolveu o token de renovação. Rode a autorização de novo.")
    token["expira_em"] = time.time() + int(token.get("expires_in", 3600)) - 60
    _gravar_token(token)
    return token


def _gravar_token(token: dict[str, Any]) -> None:
    arq = arquivo_token()
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(token), encoding="utf-8")
    try:
        os.chmod(arq, 0o600)
    except OSError:
        pass


def autorizar(abrir_navegador: bool = True, entrada=input, saida=print) -> str:
    """Fluxo completo de autorização (interativo)."""
    _cliente_oauth()
    verificador, desafio = _pkce()
    estado = secrets.token_urlsafe(16)
    recebido: dict[str, str] = {}

    class Retorno(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            if q.get("state", [""])[0] == estado:
                recebido.update({k: v[0] for k, v in q.items()})
            ok = "code" in recebido
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Pronto! O Quíron já pode usar sua agenda. Pode fechar esta aba." if ok else "Não deu certo. Volte ao Quíron e tente de novo."
            self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'><h2>{msg}</h2></body></html>".encode())

        def log_message(self, *a):  # silêncio
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Retorno)
    porta = servidor.server_address[1]
    link = link_autorizacao(porta, estado, desafio)
    if abrir_navegador:
        fio = threading.Thread(target=servidor.handle_request, daemon=True)
        fio.start()
        saida("Abrindo o navegador para você entrar na sua conta Google e permitir o acesso à agenda…")
        saida(f"(se não abrir, copie este link no navegador)\n{link}")
        webbrowser.open(link)
        fio.join(timeout=300)
    else:
        saida(f"1) Abra este link no navegador (pode ser no celular ou em outro computador):\n{link}\n")
        saida("2) Entre na conta, permita o acesso. A página final NÃO vai abrir (normal).")
        colado = entrada("3) Copie o endereço dessa página (começa com http://127.0.0.1) e cole aqui: ").strip()
        q = parse_qs(urlparse(colado).query)
        if q.get("state", [""])[0] == estado:
            recebido.update({k: v[0] for k, v in q.items()})
    servidor.server_close()
    if recebido.get("error"):
        raise AgendaIndisponivel(f"Autorização negada: {recebido['error']}")
    if "code" not in recebido:
        raise AgendaIndisponivel("Não recebi a autorização (tempo esgotado ou endereço errado). Tente de novo.")
    trocar_codigo(recebido["code"], porta, verificador)
    return "✅ Google Agenda autorizado. Token guardado em segredos/google_token.json."


# ---------------------------------------------------------------- uso
def _token(cliente_http: httpx.Client | None = None) -> str:
    if not configurado():
        raise AgendaIndisponivel(como_configurar())
    tok = json.loads(arquivo_token().read_text(encoding="utf-8"))
    if tok.get("access_token") and tok.get("expira_em", 0) > time.time():
        return tok["access_token"]
    c = _cliente_oauth()
    http = cliente_http or httpx.Client(timeout=30)
    r = http.post(URL_TOKEN, data={"client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise AgendaIndisponivel("A autorização do Google expirou ou foi revogada. Autorize de novo (Quiron Google Agenda.bat). "
                                 f"Detalhe: {r.text[:150]}")
    novo = r.json()
    tok.update(access_token=novo["access_token"], expira_em=time.time() + int(novo.get("expires_in", 3600)) - 60)
    _gravar_token(tok)
    return tok["access_token"]


def _http(cliente_http: httpx.Client | None = None) -> httpx.Client:
    return cliente_http or httpx.Client(timeout=30)


@dataclass
class Evento:
    id: str
    titulo: str
    inicio: datetime | date
    fim: datetime | date
    dia_inteiro: bool = False
    local: str = ""
    link: str = ""

    def descrever(self) -> str:
        if self.dia_inteiro:
            return f"📅 (dia todo) {self.titulo}"
        return f"📅 {self.inicio:%H:%M}–{self.fim:%H:%M} {self.titulo}" + (f" · {self.local}" if self.local else "")


def _quando(campo: dict[str, str]) -> tuple[datetime | date, bool]:
    from quiron.runtime.agendador import BRT

    if "dateTime" in campo:
        return datetime.fromisoformat(campo["dateTime"].replace("Z", "+00:00")).astimezone(BRT), False
    return date.fromisoformat(campo["date"]), True


def eventos(inicio: datetime, fim: datetime, cliente_http: httpx.Client | None = None) -> list[Evento]:
    http = _http(cliente_http)
    r = http.get(f"{API}/calendars/{agenda_id()}/events", headers={"Authorization": f"Bearer {_token(cliente_http)}"},
                 params={"timeMin": inicio.isoformat(), "timeMax": fim.isoformat(), "singleEvents": "true",
                         "orderBy": "startTime", "maxResults": 100})
    if r.status_code != 200:
        raise AgendaIndisponivel(f"Google Agenda respondeu {r.status_code}: {r.text[:150]}")
    saida = []
    for e in r.json().get("items", []):
        if e.get("status") == "cancelled":
            continue
        ini, inteiro = _quando(e.get("start", {}))
        fim_, _ = _quando(e.get("end", {}))
        saida.append(Evento(e["id"], e.get("summary", "(sem título)"), ini, fim_, inteiro, e.get("location", ""), e.get("htmlLink", "")))
    return saida


def eventos_do_dia(dia: date, cliente_http: httpx.Client | None = None) -> list[Evento]:
    from quiron.runtime.agendador import BRT

    ini = datetime.combine(dia, datetime.min.time(), tzinfo=BRT)
    return eventos(ini, ini + timedelta(days=1), cliente_http)


def criar_evento(titulo: str, inicio: datetime, fim: datetime | None = None, descricao: str = "",
                 cliente_http: httpx.Client | None = None) -> Evento:
    fim = fim or inicio + timedelta(hours=1)
    corpo = {"summary": titulo[:200], "description": (descricao + "\n\nCriado pelo Quíron").strip(),
             "start": {"dateTime": inicio.isoformat(), "timeZone": "America/Sao_Paulo"},
             "end": {"dateTime": fim.isoformat(), "timeZone": "America/Sao_Paulo"}}
    http = _http(cliente_http)
    r = http.post(f"{API}/calendars/{agenda_id()}/events", headers={"Authorization": f"Bearer {_token(cliente_http)}"}, json=corpo)
    if r.status_code not in (200, 201):
        raise AgendaIndisponivel(f"Não criei o evento ({r.status_code}): {r.text[:150]}")
    e = r.json()
    ini, _ = _quando(e["start"])
    fim_, _ = _quando(e["end"])
    return Evento(e["id"], e.get("summary", titulo), ini, fim_, False, "", e.get("htmlLink", ""))


def remover_evento(ident: str, cliente_http: httpx.Client | None = None) -> bool:
    http = _http(cliente_http)
    r = http.delete(f"{API}/calendars/{agenda_id()}/events/{ident}", headers={"Authorization": f"Bearer {_token(cliente_http)}"})
    return r.status_code in (200, 204)


def evento_de_texto(texto: str, agora: datetime | None = None, cliente_http: httpx.Client | None = None) -> Evento:
    """'quinta às 15h reunião com CLI-012 por 1h30' → evento (data/hora/duração calculadas aqui)."""
    import re

    from quiron.runtime.agendador import BRT
    from quiron.servicos.assessoria import datas

    agora = agora or datetime.now(BRT)
    duracao = timedelta(hours=1)
    if m := re.search(r"\b(?:por|durante|de)\s+(\d+)\s*h(?:oras?)?\s*(?:e\s*)?(\d{1,2})?\s*(?:min)?\b|\b(?:por|durante)\s+(\d+)\s*min(?:utos)?\b", texto, re.I):
        duracao = timedelta(hours=int(m[1]), minutes=int(m[2] or 0)) if m[1] else timedelta(minutes=int(m[3]))
        texto = (texto[:m.start()] + texto[m.end():]).strip()
    titulo, d, h = datas.extrair(texto, agora.date())
    if not h:
        raise AgendaIndisponivel("Diga o horário do evento (ex.: “quinta às 15h reunião com CLI-012”).")
    d = d or (agora.date() if (h[0], h[1]) > (agora.hour, agora.minute) else agora.date() + timedelta(days=1))
    inicio = datetime.combine(d, datetime.min.time(), tzinfo=BRT).replace(hour=h[0], minute=h[1])
    return criar_evento(titulo or "Compromisso", inicio, inicio + duracao, cliente_http=cliente_http)


# ---------------------------------------------------------------- linha de comando
def main() -> None:
    """`uv run quiron-google autorizar [--sem-navegador]` · `quiron-google testar` · `quiron-google hoje`."""
    import argparse

    from quiron.nucleo.config import carregar_config

    carregar_config()
    p = argparse.ArgumentParser(prog="quiron-google", description="Google Agenda do Quíron")
    p.add_argument("acao", choices=["autorizar", "testar", "hoje"], nargs="?", default="autorizar")
    p.add_argument("--sem-navegador", action="store_true", help="mostra o link e pede o endereço de volta (servidor sem tela)")
    a = p.parse_args()
    try:
        if a.acao == "autorizar":
            print(autorizar(abrir_navegador=not a.sem_navegador))
        itens = eventos_do_dia(date.today())
        print(f"Conexão OK. Hoje há {len(itens)} evento(s) na agenda.")
        for e in itens:
            print(" ", e.descrever())
    except AgendaIndisponivel as e:
        print(f"⚠️ {e}")
        raise SystemExit(1) from e
