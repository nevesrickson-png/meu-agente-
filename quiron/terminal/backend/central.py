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
import logging
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
        self._quedas_rapidas = 0

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
                inicio = time.time()
                codigo = self.proc.wait()
                saida.write(f"===== {_agora()} parou (código {codigo}) =====\n")
            if not self.querer:
                break
            if self._manual:  # reinício pedido na tela: volta na hora, não conta como queda
                self._manual = False
                self._quedas_rapidas = 0
                continue
            self.reinicios += 1
            self._quedas_rapidas = self._quedas_rapidas + 1 if time.time() - inicio < 60 else 0
            motivo = motivo_da_queda(self.registro(80))
            self.ultimo_erro = f"parou às {_agora()} (código {codigo})" + (f": {motivo}" if motivo else "")
            # caiu logo ao ligar 3 vezes seguidas = problema de configuração (ex.: token errado): espera mais e avisa
            self.situacao = "erro" if self._quedas_rapidas >= 3 else "religando"
            self._acordar.wait(self.espera if self._quedas_rapidas < 3 else max(self.espera, 300))
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


def motivo_da_queda(registro: str) -> str:
    """Traduz o fim do registro do bot num motivo que o Rickson entende."""
    texto = registro[-6000:]
    conhecidos = [
        (r"InvalidToken|Unauthorized", "o Telegram recusou o token do bot — confira em Chaves e contas (botão Testar)"),
        (r"Conflict|terminated by other getUpdates", "o mesmo bot está ligado em outro lugar (outro PC ou janela antiga)"),
        (r"Configure TELEGRAM_BOT_TOKEN", "faltam o token do bot ou o seu ID em Chaves e contas"),
        (r"NetworkError|ConnectError|ConnectTimeout|getaddrinfo|Name or service not known|TimedOut",
         "sem conexão com a internet/Telegram — religa sozinho quando a conexão voltar"),
        (r"MemoryError", "faltou memória no PC — feche programas pesados"),
    ]
    import re

    for padrao, motivo in conhecidos:
        if re.search(padrao, texto):
            return motivo
    linhas = [x.strip() for x in texto.splitlines() if x.strip() and not x.startswith("=====")]
    erro = next((x for x in reversed(linhas) if re.search(r"Error|Exception|Erro", x)), "")
    return erro[:200]


SUPERVISOR = Supervisor()


def copia_diaria_da_memoria(intervalo_s: float = 3600, vezes: int | None = None) -> None:
    """No PC (modo central), garante uma cópia da memória por dia mesmo sem o Telegram ligado."""
    from quiron.runtime.memoria_longa import MemoriaLonga

    n = 0
    while vezes is None or n < vezes:
        n += 1
        try:
            m = MemoriaLonga()
            hoje = datetime.now().astimezone().strftime("%Y-%m-%d")
            if not (m.pasta_copias() / hoje / m.caminho.name).exists():
                m.fazer_copia()
        except Exception:  # noqa: BLE001
            logging.exception("falha na cópia diária da memória")
        if vezes is None or n < vezes:
            time.sleep(intervalo_s)


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


# ---------------------------------------------------------------- verificar tudo
def _item(nome: str, ok: bool | None, detalhe: str, como: str = "") -> dict[str, Any]:
    """ok: True = ✔, False = ✖ (precisa agir), None = ℹ️ (informativo / opcional)."""
    return {"item": nome, "ok": ok, "detalhe": detalhe, "como": como}


def _verificar_ferramentas() -> tuple[int, dict[str, str]]:
    import asyncio

    from quiron.runtime.ferramentas_mcp import ConexaoMCP

    async def rodar() -> tuple[int, dict[str, str]]:
        async with ConexaoMCP() as c:
            return len(c.ferramentas), dict(c.falhas)

    return asyncio.run(rodar())


def verificar_tudo(testar_rede: bool = True, ferramentas: Callable[[], tuple[int, dict[str, str]]] | None = None) -> list[dict[str, Any]]:
    """Checklist completo para o dia a dia e para o primeiro teste: chaves, Telegram, IA, ferramentas, disco, memória, regras."""
    import shutil

    from quiron.nucleo import offline, regras

    itens: list[dict[str, Any]] = []
    valores = configurador.ler_valores()
    falta = configurador.faltando(valores)
    itens.append(_item("Chaves obrigatórias", not falta,
                       "todas preenchidas" if not falta else "falta: " + ", ".join(configurador.POR_CHAVE[k]["rotulo"] for k in falta),
                       "" if not falta else "Preencha em Chaves e contas e clique em Salvar."))
    if testar_rede and not offline.ativo():
        for chave, nome in [("TELEGRAM_BOT_TOKEN", "Telegram (token do bot)"), ("GEMINI_API_KEY", "IA principal (Gemini)"),
                            ("GROQ_API_KEY", "IA reserva e áudio (Groq)"), ("BRAPI_TOKEN", "Cotações (brapi)")]:
            if not valores.get(chave):
                if not configurador.POR_CHAVE[chave]["obrigatorio"]:
                    itens.append(_item(nome, None, "não configurado (opcional)"))
                continue
            r = configurador.testar(chave, valores[chave])
            itens.append(_item(nome, r["ok"], r["mensagem"], "" if r["ok"] else "Copie a chave de novo e clique em Testar."))
    tg = SUPERVISOR.estado()
    if tg["situacao"] in {"ligado", "religando", "erro"}:
        itens.append(_item("Quíron no Telegram", tg["situacao"] == "ligado",
                           {"ligado": f"ligado desde {tg['desde']}", "religando": "religando…"}.get(tg["situacao"], tg["ultimo_erro"]),
                           "" if tg["situacao"] == "ligado" else "Veja o Registro do Telegram abaixo."))
    try:
        n, falhas = (ferramentas or _verificar_ferramentas)()
        itens.append(_item("Ferramentas do Quíron (servidores MCP)", not falhas,
                           f"{n} ferramentas prontas" + (f" · com problema: {', '.join(falhas)}" if falhas else ""),
                           "" if not falhas else "Feche e abra o Quíron; se continuar, mande o Registro para o suporte."))
    except Exception as e:  # noqa: BLE001
        itens.append(_item("Ferramentas do Quíron (servidores MCP)", False, f"não subiram ({type(e).__name__}: {e})"[:200]))
    try:
        livre = shutil.disk_usage(pasta_dados().parent if pasta_dados().exists() else RAIZ).free / 1e9
        itens.append(_item("Espaço em disco", livre >= 2, f"{livre:.1f} GB livres", "" if livre >= 2 else "Libere espaço no disco."))
    except OSError:
        pass
    try:
        import psutil

        mem = psutil.virtual_memory()
        itens.append(_item("Memória do PC", mem.available / 1e9 >= 1, f"{mem.available / 1e9:.1f} GB livres de {mem.total / 1e9:.0f} GB",
                           "" if mem.available / 1e9 >= 1 else "Feche programas pesados (navegador com muitas abas, jogos)."))
    except ImportError:
        pass
    try:
        teste = pasta_dados() / ".teste-escrita"
        teste.parent.mkdir(parents=True, exist_ok=True)
        teste.write_text("ok")
        teste.unlink()
        itens.append(_item("Pasta de dados", True, str(pasta_dados())))
    except OSError as e:
        itens.append(_item("Pasta de dados", False, f"sem permissão de escrita ({e})", "Mova a pasta do Quíron para Documentos."))
    pendentes = regras.avisos()
    itens.append(_item("Regras de mercado (IR, FGC, poupança…)", None if pendentes else True,
                       f"{len(pendentes)} bloco(s) sem a sua conferência" if pendentes else "todas conferidas",
                       "Confira config/regras_mercado.yaml e preencha verificado_em (o Quíron avisa nas respostas)." if pendentes else ""))
    try:
        from quiron.runtime.memoria_longa import MemoriaLonga

        mem = MemoriaLonga()
        r, integra = mem.resumo(), mem.verificar_integridade()
        copia = r["ultima_copia"]
        recente = bool(copia) and (datetime.now().astimezone() - datetime.fromisoformat(copia)).days < 2
        itens.append(_item("Memória persistente", integra == "ok" and (recente or not r["registros"]),
                           f"{r['fatos']} fatos · {r['episodios']} conversas resumidas · {r['registros']} registros · {r['tamanho_mb']} MB · "
                           f"integridade {integra} · última cópia {copia[:16].replace('T', ' ') if copia else 'nenhuma'}",
                           "" if integra == "ok" and (recente or not r["registros"]) else
                           "No Telegram: /memoria copia (cópia agora) e /memoria estado."))
    except Exception as e:  # noqa: BLE001
        itens.append(_item("Memória persistente", False, f"não abriu ({type(e).__name__}: {e})"[:200]))
    g = GOOGLE.estado()
    itens.append(_item("Google Agenda", True if g["autorizado"] else None, "conectado" if g["autorizado"] else "não conectado (opcional)"))
    return itens


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
    funcao = {"ligar": SUPERVISOR.ligar, "desligar": SUPERVISOR.desligar, "reiniciar": SUPERVISOR.reiniciar}.get(acao)
    if funcao is None:
        raise HTTPException(404, "ação: ligar, desligar ou reiniciar")
    try:
        funcao()
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


@router.post("/verificar")
def api_verificar(request: Request) -> dict[str, Any]:
    _proteger_sistema(request)
    itens = verificar_tudo()
    return {"itens": itens, "problemas": sum(i["ok"] is False for i in itens), "quando": _agora()}


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
