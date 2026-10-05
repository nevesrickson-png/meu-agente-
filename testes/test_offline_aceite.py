"""Aceite da Fase 16 — SEM INTERNET: o Quíron consulta a biblioteca e mostra um cliente real.

Precisa do Ollama rodando com o modelo da versão offline (`ollama pull qwen2.5:3b`) e do modelo de embeddings em
dados/modelos. A internet do processo é cortada (proxy morto) e o modo offline é ligado; o navegador abre o Terminal
local, destranca o cofre, mostra o cliente real e pergunta ao Quíron local sobre um livro da biblioteca.
Rodar: `uv run pytest -m online testes/test_offline_aceite.py`."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.online
RAIZ = Path(__file__).resolve().parents[1]
CAPTURAS = Path(os.environ.get("QUIRON_CAPTURAS", RAIZ / "dados" / "capturas"))
SENHA = "minha frase secreta do cofre"
LIVRO = [
    ("Capítulo 1 — Duration", "Duration é o prazo médio ponderado dos fluxos de caixa de um título, pesado pelo valor "
     "presente de cada fluxo. Ela mede a sensibilidade do preço do título à variação da taxa de juros: com duration "
     "modificada de 5 anos, uma alta de 1 ponto percentual na taxa derruba o preço em cerca de 5%. Títulos longos e com "
     "cupom baixo têm duration maior e, por isso, oscilam mais."),
    ("Capítulo 2 — Convexidade", "Convexidade é a curvatura da relação entre preço e taxa. Ela faz o preço subir mais "
     "quando a taxa cai do que cai quando a taxa sobe, para a mesma variação. É a correção de segunda ordem da duration."),
]


def _ollama_ok() -> bool:
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3).json()
        return any(m["name"].startswith("qwen2.5:3b") for m in tags.get("models", []))
    except (httpx.HTTPError, ValueError):
        return False


def _porta() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(not _ollama_ok(), reason="precisa do Ollama com qwen2.5:3b")
def test_aceite_sem_internet_biblioteca_e_cliente_real(tmp_path):
    import pymupdf

    dados, bib = tmp_path / "dados", tmp_path / "bib"
    (bib / "entrada").mkdir(parents=True)
    dados.mkdir()
    modelos = RAIZ / "dados" / "modelos"
    if modelos.exists():
        (dados / "modelos").symlink_to(modelos, target_is_directory=True)
    doc = pymupdf.open()
    for titulo, texto in LIVRO:
        pg = doc.new_page()
        pg.insert_textbox(pymupdf.Rect(50, 50, 545, 800), f"{titulo}\n\n{texto}", fontsize=11)
    doc.set_metadata({"title": "Manual de Renda Fixa do Quíron", "author": "Quíron Teste"})
    doc.save(bib / "entrada" / "manual-renda-fixa.pdf")

    env = {**os.environ, "QUIRON_DADOS": str(dados), "QUIRON_BIBLIOTECA": str(bib), "QUIRON_COFRE": str(tmp_path / "cofre" / "c.cofre"),
           "QUIRON_MODO": "offline", "UV_OFFLINE": "1", "HF_HUB_OFFLINE": "1",
           # sem internet: qualquer saída para fora morre no proxy inexistente
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
           "http_proxy": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    preparo = ("from quiron.servicos.biblioteca.ingestao import ingerir_pasta; r = ingerir_pasta(); "
               "from quiron.servicos.planejamento import ficha; "
               "ficha.salvar({'cliente': 'CLI-012', 'idade': 52, 'ocupacao': 'profissional_liberal', 'uf': 'SP', 'perfil': 'moderado', "
               "'renda_mensal_bruta': 45000, 'despesas_mensais': 22000}); print('ok')")
    saida = subprocess.run([sys.executable, "-c", preparo], cwd=RAIZ, env=env, capture_output=True, text=True, timeout=600)
    assert saida.returncode == 0, saida.stderr[-2000:]
    sem_rede = subprocess.run([sys.executable, "-c", "import httpx; httpx.get('https://www.bcb.gov.br', timeout=5)"], env=env,
                              capture_output=True, text=True)
    assert sem_rede.returncode != 0  # confirma: o processo não alcança a internet

    porta = _porta()
    proc = subprocess.Popen([sys.executable, "-m", "quiron.terminal.backend.app", "--porta", str(porta), "--sem-navegador"],
                            cwd=RAIZ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        from playwright.sync_api import sync_playwright

        CAPTURAS.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            exe = "/opt/pw-browsers/chromium"
            nav = p.chromium.launch(executable_path=exe) if Path(exe).exists() else p.chromium.launch()
            pg = nav.new_page(viewport={"width": 1500, "height": 1000})
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.goto(f"http://127.0.0.1:{porta}")
            pg.locator(".selo-offline").wait_for(timeout=15_000)
            cli = pg.locator(".painel").filter(has=pg.locator(".painel-titulo", has_text="CLI")).first
            cli.locator("input[name=senha]").wait_for(timeout=15_000)
            cli.locator("input[name=senha]").fill(SENHA)
            cli.locator("button[type=submit]").click()
            cli.locator("summary").click()
            cli.locator("[data-novo] input[name=codigo]").fill("CLI-012")
            cli.locator("[data-novo] input[name=nome]").fill("Marcos Antônio Pereira")
            cli.locator("[data-novo] input[name=cidade]").fill("Campinas")
            cli.locator("[data-novo] button[type=submit]").click()
            cli.locator("tr[data-cod='CLI-012']").click()
            cli.locator("text=DOSSIÊ DE REUNIÃO — CLI-012").wait_for(timeout=30_000)
            assert "Marcos Antônio Pereira" in cli.inner_text() and "52 anos" in cli.inner_text()

            chat = pg.locator(".painel").filter(has=pg.locator(".painel-titulo", has_text="Chat")).first
            chat.locator("textarea").fill("Segundo a minha biblioteca, o que é duration? Cite o livro.")
            chat.locator("button[type=submit]").click()
            resposta = chat.locator(".msg.quiron").last
            chat.locator(".msg.quiron .memoria").last.wait_for(timeout=600_000)
            texto = resposta.inner_text()
            assert "quiron_biblioteca" in texto, texto
            assert "Manual de Renda Fixa" in texto and ("sensibilidade" in texto.lower() or "prazo médio" in texto.lower())
            pg.screenshot(path=str(CAPTURAS / "offline-aceite.png"), full_page=True)
            (CAPTURAS / "offline-aceite.txt").write_text(texto, encoding="utf-8")
            assert not erros, erros
            nav.close()
    finally:
        proc.terminate()
