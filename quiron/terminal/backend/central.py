"""Central do Quíron: tudo o que antes eram janelas soltas, dentro do Terminal (aba CONFIGURAÇÕES).

- **Telegram**: o bot roda como processo filho supervisionado (liga, desliga, reinicia, religa sozinho em 30 s se
  cair, registro em `dados/logs/telegram.log`). Só quando o Terminal foi aberto pelo atalho Quiron (`--central`);
  no servidor (Docker) o bot é outro serviço e aqui só aparece "gerenciado fora".
- **Chaves e contas**: as mesmas regras do configurador (`.env` preservado, segredos mascarados); salvar aplica na
  hora e reinicia o bot.
- **Google Agenda**: envio da credencial e autorização sem sair da tela.
- **Versão offline**: verificação e troca de modo (o lançador `quiron` reinicia o Terminal no outro modo).
- **Início automático** (Windows) e versão instalada.

Segurança: toda rota daqui exige o cabeçalho da tela; as que mexem em chaves/sistema só valem no próprio PC
(ou com TERMINAL_SENHA, quando o Terminal já pede login)."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Body, HTTPException, Request

from quiron.configurador import app as configurador
from quiron.nucleo.config import RAIZ, carregar_config, pasta_dados

router = APIRouter(prefix="/api/sistema")
CLIENTES_LOCAIS = {"127.0.0.1", "::1", "testclient"}
CODIGO_TROCA_MODO = 3  # o lançador `quiron` entende: reinicie no modo gravado em dados/modo_proximo
MARCA_BOT = "quiron.runtime.telegram_bot"


def _agora() -> str:
    return datetime.now().strftime("%d/%m %H:%M:%S")


# ---------------------------------------------------------------- supervisor do bot
class Supervisor:
    """Mantém um processo filho ligado (o bot do Telegram), religando se cair."""

    def __init__(self, comando: list[str] | None = None, espera: float = 30, log: Path | None = None) -> None:
        self.comando = comando or [sys.executable, "-m", MARCA_BOT]
        self.espera = espera
        self._log = log
        self.gerenciado = False  # True só no Terminal aberto pelo atalho (modo central)
        self.proc: subprocess.Popen | None = None
        self.querer = False
        self.situacao = "desligado"
        self.desde = ""
        self.reinicios = 0
        self.ultimo_erro = ""
        self._trava = threading.Lock()
        self._acordar = threading.Event()
        self._fio: threading.Thread | None = None
        self._manual = False

    def log(self) -> Path:
        return self._log or pasta_dados() / "logs" / "telegram.log"

    # -- outro bot ligado (janela antiga, outro Terminal)? dois bots no mesmo token brigam pelas mensagens
    def outro_bot(self) -> int | None:
        try:
            import psutil
        except ImportError:
            return None
        meu = os.getpid()
        filho = self.proc.pid if self.proc and self.proc.poll() is None else None
        for p in psutil.process_iter(["pid", "ppid", "cmdline"]):
            try:
                cmd = " ".join(p.info["cmdline"] or [])
                if p.info["pid"] in {meu, filho} or not (MARCA_BOT in cmd or "quiron-telegram" in cmd):
                    continue
                if MARCA_BOT in cmd and not psutil.pid_exists(p.info["ppid"] or 0):
                    p.terminate()  # órfão de um Terminal fechado à força: pode encerrar
                    continue
                return p.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def ligar(self) -> None:
        if not self.gerenciado:
            raise ValueError("Aqui o Telegram é ligado por fora (servidor). Abra o Quíron pelo atalho Quiron no PC.")
        from quiron.nucleo import offline

        if offline.ativo():
            raise ValueError("Na versão offline o Telegram fica desligado (não há internet).")
        falta = configurador.faltando(configurador.ler_valores())
        if falta:
            raise ValueError("Falta preencher: " + ", ".join(configurador.POR_CHAVE[k]["rotulo"] for k in falta))
        if (pid := self.outro_bot()) is not None:
            raise ValueError(f"Já existe outro Quíron ligado no Telegram (processo {pid}). Feche a janela antiga e tente de novo.")
        with self._trava:
            self.querer = True
            if self._fio is None or not self._fio.is_alive():
                self._fio = threading.Thread(target=self._laco, name="supervisor-telegram", daemon=True)
                self._fio.start()
            self._acordar.set()

    def desligar(self) -> None:
        with self._trava:
            self.querer = False
            self._acordar.set()
            self._parar_proc()
            self.situacao = "desligado"

    def reiniciar(self) -> None:
        with self._trava:
            self._manual = self.situacao == "ligado"
            self._parar_proc()  # o laço percebe e sobe de novo na hora
        self.ligar()

    def _parar_proc(self) -> None:
        p = self.proc
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()

    def _abrir_log(self):
        arq = self.log()
        arq.parent.mkdir(parents=True, exist_ok=True)
        if arq.exists() and arq.stat().st_size > 2_000_000:
            arq.replace(arq.with_suffix(".log.1"))
        return open(arq, "a", encoding="utf-8", errors="replace")

    def _laco(self) -> None:
        while self.querer:
            self._acordar.clear()
            with self._abrir_log() as saida:
                saida.write(f"\n===== {_agora()} ligando o Quíron no Telegram =====\n")
                saida.flush()
                env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
                try:
                    self.proc = subprocess.Popen(self.comando, stdout=saida, stderr=subprocess.STDOUT, cwd=RAIZ, env=env)
                except OSError as e:
                    self.ultimo_erro, self.situacao, self.querer = f"não consegui iniciar: {e}", "erro", False
                    return
                self.situacao, self.desde = "ligado", _agora()
                codigo = self.proc.wait()
                saida.write(f"===== {_agora()} parou (código {codigo}) =====\n")
            if not self.querer:
                break
            if self._manual:  # reinício pedido na tela: volta na hora, não conta como queda
                self._manual = False
                continue
            self.reinicios += 1
            self.ultimo_erro = f"parou às {_agora()} (código {codigo})"
            self.situacao = "religando"
            self._acordar.wait(self.espera)  # "Ligar"/"Reiniciar" na tela acorda antes
        self.situacao = "desligado"

    def registro(self, linhas: int = 200) -> str:
        arq = self.log()
        if not arq.exists():
            return ""
        with open(arq, encoding="utf-8", errors="replace") as f:
            return "".join(deque(f, maxlen=linhas))

    def estado(self) -> dict[str, Any]:
        from quiron.nucleo import offline

        if not self.gerenciado:
            situacao = "externo"
        elif offline.ativo():
            situacao = "offline"
        elif self.situacao == "desligado" and configurador.faltando(configurador.ler_valores()):
            situacao = "sem_config"
        else:
            situacao = self.situacao
        return {"situacao": situacao, "desde": self.desde if situacao == "ligado" else "", "reinicios": self.reinicios,
                "ultimo_erro": self.ultimo_erro, "pid": self.proc.pid if self.proc and self.proc.poll() is None else None}


SUPERVISOR = Supervisor()


# ---------------------------------------------------------------- proteção
def _proteger_sistema(request: Request) -> None:
    """Cabeçalho da tela + (próprio PC ou Terminal com senha). Chaves nunca mudam por um endereço aberto."""
    from quiron.terminal.backend import app as terminal

    terminal._proteger(request)
    cliente = request.client.host if request.client else ""
    if cliente not in CLIENTES_LOCAIS and not terminal._senha():
        raise HTTPException(403, "Configurações só no próprio PC (ou com TERMINAL_SENHA definida).")


def _local(request: Request) -> bool:
    return (request.client.host if request.client else "") in CLIENTES_LOCAIS


# ---------------------------------------------------------------- chaves (.env)
def aplicar_no_processo(novos: dict[str, str]) -> None:
    """O .env mudou: atualiza o ambiente deste processo (o bot nasce dele) e recarrega a configuração."""
    for k, v in novos.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    carregar_config.cache_clear()


def _depois_de_salvar(novos: dict[str, str]) -> str:
    aplicar_no_processo(novos)
    completo = not configurador.faltando(configurador.ler_valores())
    if not SUPERVISOR.gerenciado or not completo:
        return "" if SUPERVISOR.gerenciado else "Salvo. No servidor, reinicie o serviço do agente para usar as chaves novas."
    try:
        if SUPERVISOR.querer:
            SUPERVISOR.reiniciar()
            return "Salvo. O Telegram foi reiniciado com as chaves novas."
        SUPERVISOR.ligar()
        return "Salvo. O Quíron ligou no Telegram — mande uma mensagem para ele."
    except ValueError as e:
        return f"Salvo. {e}"


# ---------------------------------------------------------------- Google Agenda
class _Google:
    def __init__(self) -> None:
        self.andamento = False
        self.link = ""
        self.resultado = ""
        self.ok: bool | None = None

    def estado(self) -> dict[str, Any]:
        from quiron.servicos.organizacao import google_agenda as g

        credencial, erro = g.arquivo_cliente().exists(), ""
        if credencial:
            try:
                g._cliente_oauth()
            except g.AgendaIndisponivel as e:
                credencial, erro = False, str(e)
        return {"credencial": credencial, "erro_credencial": erro, "autorizado": g.arquivo_token().exists(),
                "agenda": g.agenda_id(), "andamento": self.andamento, "link": self.link if self.andamento else "",
                "resultado": self.resultado, "ok": self.ok}

    def guardar_credencial(self, bruto: bytes) -> None:
        from quiron.servicos.organizacao import google_agenda as g

        if len(bruto) > 100_000:
            raise ValueError("Arquivo grande demais para ser a credencial do Google.")
        try:
            dados = json.loads(bruto.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("Esse arquivo não é o JSON baixado do Google.") from e
        corpo = dados.get("installed") or dados.get("web") if isinstance(dados, dict) else None
        if not isinstance(corpo, dict) or not corpo.get("client_id"):
            raise ValueError("Esse JSON não é a credencial OAuth (falta client_id). Baixe em Credenciais → ID do cliente OAuth → Baixar JSON.")
        arq = g.arquivo_cliente()
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_bytes(bruto)
        try:
            os.chmod(arq, 0o600)
        except OSError:
            pass

    def conectar(self, autorizar: Callable[..., str] | None = None) -> None:
        from quiron.servicos.organizacao import google_agenda as g

        if self.andamento:
            return
        g._cliente_oauth()  # credencial ok antes de começar (erro vai direto para a tela)
        self.andamento, self.link, self.resultado, self.ok = True, "", "", None

        def abrir(link: str) -> None:
            self.link = link
            import webbrowser

            webbrowser.open(link)

        def rodar() -> None:
            try:
                self.resultado, self.ok = (autorizar or g.autorizar)(abrir_navegador=True, saida=lambda *_: None, abrir=abrir), True
            except Exception as e:  # noqa: BLE001 — a mensagem vai para a tela
                self.resultado, self.ok = str(e), False
            finally:
                self.andamento = False

        threading.Thread(target=rodar, name="google-autorizar", daemon=True).start()

    def desconectar(self) -> None:
        from quiron.servicos.organizacao import google_agenda as g

        g.arquivo_token().unlink(missing_ok=True)
        self.resultado, self.ok = "Desconectado. O token foi apagado deste PC.", True


GOOGLE = _Google()


# ---------------------------------------------------------------- modo (normal/offline)
def arquivo_modo() -> Path:
    return pasta_dados() / "modo_proximo"


def ler_modo_pedido(padrao: str = "normal") -> str:
    try:
        modo = arquivo_modo().read_text(encoding="utf-8").strip()
    except OSError:
        return padrao
    return modo if modo in {"normal", "offline"} else padrao


SAIR: Callable[[int], None] | None = None  # definido pelo main do Terminal no modo central


def pedir_troca_de_modo(modo: str) -> None:
    if modo not in {"normal", "offline"}:
        raise ValueError("modo: normal ou offline")
    if not (SUPERVISOR.gerenciado and os.environ.get("QUIRON_CENTRAL") == "1" and SAIR):
        raise ValueError("Para trocar de modo, abra o Quíron pelo atalho Quiron (ou Quiron - Offline).")
    arquivo_modo().parent.mkdir(parents=True, exist_ok=True)
    arquivo_modo().write_text(modo, encoding="utf-8")
    SUPERVISOR.desligar()
    threading.Timer(0.8, lambda: SAIR and SAIR(CODIGO_TROCA_MODO)).start()


# ---------------------------------------------------------------- início automático (Windows)
def _atalho_inicio() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Quiron.lnk"


def inicio_automatico() -> dict[str, Any]:
    if platform.system() != "Windows":
        return {"disponivel": False, "ligado": False}
    return {"disponivel": True, "ligado": _atalho_inicio().exists()}


def definir_inicio_automatico(ligar: bool) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise ValueError("Início automático só existe no Windows.")
    atalho = _atalho_inicio()
    if not ligar:
        atalho.unlink(missing_ok=True)
        return inicio_automatico()
    alvo = RAIZ / "Abrir Quiron.bat"
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:Q_ATALHO); $s.TargetPath=$env:Q_ALVO; "
              "$s.WorkingDirectory=$env:Q_PASTA; $s.WindowStyle=7; $s.Save()")
    env = {**os.environ, "Q_ATALHO": str(atalho), "Q_ALVO": str(alvo), "Q_PASTA": str(RAIZ)}
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not atalho.exists():
        raise ValueError("Não consegui criar o atalho de início automático: " + (r.stderr or "").strip()[:200])
    subprocess.run(["powercfg", "/change", "standby-timeout-ac", "0"], capture_output=True, timeout=30)  # não dormir na tomada
    return inicio_automatico()


# ---------------------------------------------------------------- versão
def versao() -> dict[str, str]:
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%h|%cd", "--date=format:%d/%m/%Y %H:%M"], cwd=RAIZ,
                           capture_output=True, text=True, timeout=5)
        codigo, data = (r.stdout.strip().split("|") + [""])[:2] if r.returncode == 0 else ("", "")
    except (OSError, subprocess.TimeoutExpired):
        codigo, data = "", ""
    return {"codigo": codigo, "data": data, "pasta": str(RAIZ)}


# ---------------------------------------------------------------- rotas
def _resumo() -> dict[str, Any]:
    from quiron.nucleo import offline

    valores = configurador.ler_valores()
    return {"telegram": SUPERVISOR.estado(), "offline": offline.ativo(), "config_completa": not configurador.faltando(valores),
            "central": SUPERVISOR.gerenciado}


@router.get("/resumo")
def api_resumo() -> dict[str, Any]:
    """Selo da barra de abas (qualquer aba): Telegram ligado? Faltam chaves? Modo?"""
    return _resumo()


@router.get("/estado")
def api_estado(request: Request) -> dict[str, Any]:
    _proteger_sistema(request)
    from quiron.nucleo import offline

    cfg = carregar_config()
    return {**_resumo(), "config": configurador.estado(), "google": GOOGLE.estado(), "inicio": inicio_automatico(),
            "versao": versao(), "modelos": cfg.modelos, "modelo_offline": offline.modelo() if offline.ativo() else "",
            "local": _local(request)}


@router.post("/config/salvar")
def api_config_salvar(request: Request, corpo: dict = Body(...)) -> dict[str, Any]:
    _proteger_sistema(request)
    try:
        novos = configurador.salvar_valores(corpo.get("valores") or {})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    mensagem = _depois_de_salvar(novos)
    return {"config": configurador.estado(), "mensagem": mensagem, "telegram": SUPERVISOR.estado()}


@router.post("/config/apagar")
def api_config_apagar(request: Request, corpo: dict = Body(...)) -> dict[str, Any]:
    _proteger_sistema(request)
    chave = corpo.get("chave")
    if chave not in configurador.POR_CHAVE or configurador.POR_CHAVE[chave]["obrigatorio"]:
        raise HTTPException(400, "campo desconhecido ou obrigatório")
    configurador.atualizar_env({chave: ""})
    aplicar_no_processo({chave: ""})
    return {"config": configurador.estado()}


@router.post("/config/testar")
def api_config_testar(request: Request, corpo: dict = Body(...)) -> dict[str, Any]:
    _proteger_sistema(request)
    chave = str(corpo.get("chave", ""))
    valor = str(corpo.get("valor") or "").strip() or configurador.ler_valores().get(chave, "")
    return configurador.testar(chave, valor)


@router.post("/config/descobrir_id")
def api_config_descobrir(request: Request, corpo: dict = Body(...)) -> dict[str, Any]:
    _proteger_sistema(request)
    token = str(corpo.get("token") or "").strip() or configurador.ler_valores().get("TELEGRAM_BOT_TOKEN", "")
    pausado = SUPERVISOR.querer and SUPERVISOR.situacao == "ligado"
    if pausado:  # o bot ligado "consome" as mensagens: pausa, lê e religa
        SUPERVISOR.desligar()
    try:
        return configurador.descobrir_ids(token)
    finally:
        if pausado:
            try:
                SUPERVISOR.ligar()
            except ValueError:
                pass


@router.post("/telegram/{acao}")
def api_telegram(request: Request, acao: str) -> dict[str, Any]:
    _proteger_sistema(request)
    try:
        {"ligar": SUPERVISOR.ligar, "desligar": SUPERVISOR.desligar, "reiniciar": SUPERVISOR.reiniciar}[acao]()
    except KeyError:
        raise HTTPException(404, "ação: ligar, desligar ou reiniciar")
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    time.sleep(0.3)
    return SUPERVISOR.estado()


@router.get("/telegram/registro")
def api_telegram_registro(request: Request, linhas: int = 200) -> dict[str, Any]:
    _proteger_sistema(request)
    return {"texto": SUPERVISOR.registro(max(20, min(linhas, 2000))), "arquivo": str(SUPERVISOR.log())}


@router.get("/google")
def api_google(request: Request) -> dict[str, Any]:
    _proteger_sistema(request)
    return GOOGLE.estado()


@router.post("/google/credencial")
async def api_google_credencial(request: Request) -> dict[str, Any]:
    _proteger_sistema(request)
    try:
        GOOGLE.guardar_credencial(await request.body())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return GOOGLE.estado()


@router.post("/google/conectar")
def api_google_conectar(request: Request) -> dict[str, Any]:
    _proteger_sistema(request)
    if not _local(request):
        raise HTTPException(403, "Conecte o Google no próprio PC (a volta da autorização é para 127.0.0.1).")
    from quiron.servicos.organizacao import google_agenda as g

    try:
        GOOGLE.conectar()
    except g.AgendaIndisponivel as e:
        raise HTTPException(400, str(e)) from e
    return GOOGLE.estado()


@router.post("/google/desconectar")
def api_google_desconectar(request: Request) -> dict[str, Any]:
    _proteger_sistema(request)
    GOOGLE.desconectar()
    return GOOGLE.estado()


@router.get("/offline/verificar")
def api_offline_verificar(request: Request) -> dict[str, Any]:
    _proteger_sistema(request)
    from quiron.servicos.offline import cli

    itens = [{"item": n, "ok": ok, "detalhe": d} for n, ok, d in cli.verificar()]
    return {"itens": itens, "pronto": all(i["ok"] for i in itens)}


@router.post("/modo")
def api_modo_trocar(request: Request, corpo: dict = Body(...)) -> dict[str, Any]:
    _proteger_sistema(request)
    try:
        pedir_troca_de_modo(str(corpo.get("modo", "")))
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "mensagem": "Reiniciando o Quíron no outro modo… a tela volta sozinha em alguns segundos."}


@router.post("/inicio_automatico")
def api_inicio(request: Request, corpo: dict = Body(...)) -> dict[str, Any]:
    _proteger_sistema(request)
    if not _local(request):
        raise HTTPException(403, "Só no próprio PC.")
    try:
        return definir_inicio_automatico(bool(corpo.get("ligar")))
    except (ValueError, OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(400, str(e)) from e
