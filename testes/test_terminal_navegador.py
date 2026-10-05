"""Teste de aceite da Fase 4 num navegador de verdade (Chromium): abre o Terminal, digita PETR4 e CURV
e confere que os painéis recebem dados e se atualizam sozinhos. Precisa de internet: `uv run pytest -m online`."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.online
RAIZ = Path(__file__).resolve().parents[1]
CAPTURAS = Path(os.environ.get("QUIRON_CAPTURAS", RAIZ / "dados" / "capturas"))


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    porta = _porta_livre()
    env = {**os.environ, "QUIRON_DADOS": str(tmp_path_factory.mktemp("dados"))}
    proc = subprocess.Popen([sys.executable, "-m", "quiron.terminal.backend.app", "--porta", str(porta), "--sem-navegador"],
                            cwd=RAIZ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    yield f"http://127.0.0.1:{porta}"
    proc.terminate()


def _chromium(p):
    caminho = "/opt/pw-browsers/chromium"
    exe = None
    if Path(caminho).exists():
        achados = sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))
        exe = str(achados[-1]) if achados else None
    return p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()


def test_petr4_e_curv_atualizam_sozinhos(servidor):
    from playwright.sync_api import sync_playwright

    CAPTURAS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        nav = _chromium(p)
        pagina = nav.new_page(viewport={"width": 1600, "height": 1000})
        erros = []
        pagina.on("pageerror", lambda e: erros.append(str(e)))
        pagina.goto(servidor)
        pagina.wait_for_selector(".painel", timeout=10_000)
        pagina.evaluate("localStorage.clear()")

        pagina.keyboard.press("Control+k")
        pagina.keyboard.type("PETR4")
        pagina.keyboard.press("Enter")
        pagina.keyboard.press("Control+k")
        pagina.keyboard.type("CURV")
        pagina.keyboard.press("Enter")

        ativo = pagina.locator(".painel").filter(has=pagina.locator(".painel-titulo", has_text="PETR4")).last
        curva = pagina.locator(".painel").filter(has=pagina.locator(".painel-titulo", has_text="CURV")).last
        ativo.locator(".grande").wait_for(timeout=60_000)
        curva.locator("svg polyline").first.wait_for(timeout=60_000)
        assert "R$" in ativo.locator(".grande").inner_text()
        assert "ANBIMA" in curva.locator(".painel-rodape").inner_text() or "Tesouro" in curva.locator(".painel-rodape").inner_text()

        # atualização automática: o painel de status (15 s) muda o horário sem recarregar a página
        status = pagina.locator(".painel").filter(has=pagina.locator(".painel-titulo", has_text="Status")).first
        status.locator(".painel-sub[title^='Atualizado']").wait_for(timeout=30_000)
        antes = status.locator(".painel-sub").get_attribute("title")
        pagina.wait_for_function("(a) => [...document.querySelectorAll('.painel-sub')].some(e => (e.title || '').startsWith('Atualizado') && e.title !== a)",
                                 arg=antes, timeout=40_000)
        juros = pagina.locator(".painel").filter(has=pagina.locator(".painel-titulo", has_text="Juros")).first
        juros.locator(".kpi-v").first.wait_for(timeout=30_000)  # Selic/CDI aparecem logo
        juros.locator("text=Tesouro Direto (").wait_for(timeout=90_000)  # o Tesouro chega sozinho depois
        pagina.wait_for_timeout(2000)
        pagina.evaluate("scrollTo(0, 0)")
        pagina.wait_for_timeout(500)
        pagina.screenshot(path=str(CAPTURAS / "terminal-aceite.png"))
        pagina.screenshot(path=str(CAPTURAS / "terminal-aceite-completo.png"), full_page=True)
        assert not erros, erros
        nav.close()


def test_aceite_fase12_wege3_dcf_aparece_em_rpt(servidor):
    """Aceite da Fase 12: `WEGE3 DCF` dispara a análise e o relatório aparece em `RPT` (com PDF)."""
    from playwright.sync_api import sync_playwright

    CAPTURAS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        nav = _chromium(p)
        pagina = nav.new_page(viewport={"width": 1600, "height": 1000})
        erros = []
        pagina.on("pageerror", lambda e: erros.append(str(e)))
        pagina.goto(servidor)
        pagina.wait_for_selector(".painel", timeout=10_000)
        pagina.evaluate("localStorage.clear()")
        pagina.keyboard.press("Control+k")
        pagina.keyboard.type("WEGE3 DCF")
        pagina.keyboard.press("Enter")

        rpt = pagina.locator(".painel").filter(has=pagina.locator(".painel-titulo", has_text="RPT")).last
        linha = rpt.locator("tr.destaque")
        linha.wait_for(timeout=15_000)
        assert "WEGE3" in pagina.inner_text("#aviso") or "fila" in linha.inner_text()
        linha.locator("a", has_text="PDF").wait_for(timeout=360_000)  # o RPT se atualiza sozinho até ficar pronta
        assert "WEG" in linha.inner_text() and "pronta" in linha.inner_text()
        href = linha.locator("a", has_text="PDF").get_attribute("href")
        pdf = pagina.request.get(servidor + href)
        assert pdf.status == 200 and pdf.body()[:4] == b"%PDF"

        pagina.keyboard.press("Control+k")
        pagina.keyboard.type("WEGE3 FA")
        pagina.keyboard.press("Enter")
        fa = pagina.locator(".painel").filter(has=pagina.locator(".painel-titulo", has_text="WEGE3 FA")).last
        fa.locator("text=Receita").wait_for(timeout=120_000)
        assert "Uso interno" in fa.locator(".painel-rodape").inner_text()
        pagina.evaluate("scrollTo(0, 0)")
        pagina.screenshot(path=str(CAPTURAS / "terminal-v2-aceite.png"), full_page=True)
        assert not erros, erros
        nav.close()
