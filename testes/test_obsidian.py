"""Cérebro (cofre do Obsidian) — etapa A: pasta e regras de escrita, índice com links/tags, /nota em arquivo e
migração das antigas, nota diária que preserva o texto do Rickson, memória editável pelo Obsidian, LGPD, rotas e
Terminal. Sem internet e sem IA."""

import os
import time
from datetime import date, datetime

import pytest

from quiron.servicos.obsidian import diario, indice, rotina
from quiron.servicos.obsidian import pasta as P


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path / "dados"))
    monkeypatch.delenv("QUIRON_CEREBRO", raising=False)
    monkeypatch.setattr(indice, "_ultima", {})
    monkeypatch.setattr(rotina, "_preparado", set())
    return tmp_path


def _escrever(rel: str, texto: str) -> None:
    arq = P.pasta() / rel
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(texto, encoding="utf-8")


def test_estrutura_criada_sem_sobrescrever(tmp_path):
    raiz = P.garantir()
    for sub in ("Minhas notas/Entrada", "Quíron/Diário", "Quíron/Memória", "Modelos", ".obsidian"):
        assert (raiz / sub).is_dir()
    (raiz / "Modelos" / "Tese.md").write_text("meu modelo", encoding="utf-8")
    (raiz / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    P.garantir()
    assert (raiz / "Modelos" / "Tese.md").read_text(encoding="utf-8") == "meu modelo"
    assert (raiz / ".obsidian" / "app.json").read_text(encoding="utf-8") == "{}"


def test_regras_de_escrita_e_caminhos():
    P.garantir()
    for ruim in ("../fora.md", "C:/Windows/x.md", "Minhas notas/../../x.md", "a\\..\\..\\x.md", ""):
        with pytest.raises(P.EscritaRecusada):
            P.caminho(ruim)
    assert P.pasta().resolve() in P.caminho("/etc/passwd").parents  # barra no começo fica DENTRO do cofre
    with pytest.raises(P.EscritaRecusada):
        P.gravar_quiron("Minhas notas/x.md", "não pode")
    with pytest.raises(P.EscritaRecusada):
        P.criar_nova("Minhas notas", "x", "só na Entrada")
    a = P.criar_nova(P.ENTRADA, "Ideia: CON?", "1")
    b = P.criar_nova(P.ENTRADA, "Ideia: CON?", "2")
    assert a != b and a.read_text(encoding="utf-8") == "1" and b.name.endswith(" 2.md")
    assert P.nome_arquivo("CON") == "CON (nota)" and P.nome_arquivo('a<b>:c"d|e?*[[f]]#g') == "a b c d e f g"


def test_indice_busca_links_tags_e_quem_cita():
    _escrever("Minhas notas/Duration.md", "---\ntags: [renda-fixa]\n---\n# Duration\nSensibilidade do preço à taxa. Ver [[Convexidade|curvatura]].\n")
    _escrever("Minhas notas/Convexidade.md", "A segunda derivada. #estudo\n```\n#naoetag [[naoelink]]\n```\n")
    _escrever("Minhas notas/Imunização.md", "Casar [[duration]] do ativo e do passivo; ver [[Nota que não existe]].\n")
    _escrever(".obsidian/ignorar.md", "duration escondida")
    indice.atualizar(forcar=True)
    assert [n.titulo for n in indice.buscar("sensibilidade preco")] == ["Duration"]  # sem acento acha com acento
    assert {n.titulo for n in indice.buscar("duration")} == {"Duration", "Imunização"}
    assert [n.titulo for n in indice.buscar("#estudo")] == ["Convexidade"] and indice.buscar("#naoetag") == []
    assert [n.titulo for n in indice.buscar("#renda-fixa")] == ["Duration"]
    nota, texto = indice.obter("duration")
    assert "Sensibilidade" in texto
    assert [n.titulo for n in indice.quem_cita(nota)] == ["Imunização"]
    saem, faltam = indice.ligacoes(indice.obter("Imunização")[0])
    assert [n.titulo for n in saem] == ["Duration"] and faltam == ["nota que não existe"]
    assert indice.ligacoes(indice.obter("Convexidade")[0]) == ([], [])  # link dentro de código não conta
    # mexer e apagar refletem no índice
    time.sleep(0.01)
    _escrever("Minhas notas/Convexidade.md", "Agora fala de gama.\n")
    (P.pasta() / "Minhas notas" / "Imunização.md").unlink()
    r = indice.atualizar(forcar=True)
    assert r["alteradas"] == 1 and r["removidas"] == 1
    assert indice.buscar("derivada") == [] and indice.quem_cita(nota) == []


def test_nota_rapida_vai_para_o_cerebro_e_antigas_migram():
    from quiron.servicos.organizacao import notas
    from quiron.servicos.organizacao.banco import conectar

    with conectar() as con:
        con.execute("INSERT INTO notas(texto, tags, cliente, criada_em) VALUES (?,?,?,?)",
                    ("Pauta antiga sobre previdência #conteudo", "conteudo", "", "2026-09-30T08:15:00"))
    n = notas.criar("Ideia: explicar convexidade com gangorra #estudo", datetime(2026, 10, 8, 9, 30))
    arquivos = sorted(p.name for p in (P.pasta() / P.ENTRADA).glob("*.md"))
    assert arquivos == ["2026-09-30 0815 Pauta antiga sobre previdência.md", "2026-10-08 0930 Ideia explicar convexidade com gangorra.md"]
    with conectar() as con:
        assert con.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0  # saiu do banco só depois de virar arquivo
    assert [x.id for x in notas.buscar("gangorra")] == [n.id] and notas.buscar("#conteudo")[0].criada_em.startswith("2026-09-30")
    fm, corpo = P.ler_frontmatter((P.pasta() / P.ENTRADA / arquivos[1]).read_text(encoding="utf-8"))
    assert fm["tags"] == ["estudo"] and fm["criada"] == "2026-10-08T09:30:00" and corpo.startswith("Ideia:")
    _escrever("Minhas notas/Minha.md", "gangorra também aqui")
    indice.atualizar(forcar=True)
    minha = next(x for x in notas.buscar("gangorra") if x.caminho == "Minhas notas/Minha.md")
    assert not notas.remover(minha.id) and (P.pasta() / "Minhas notas" / "Minha.md").exists()  # nota dele não se apaga daqui
    assert notas.remover(n.id) and not (P.pasta() / P.ENTRADA / arquivos[1]).exists()


def test_diario_preserva_o_texto_dele_e_deixa_clientes_de_fora(monkeypatch):
    from quiron.servicos.organizacao import tarefas

    dia = date(2026, 10, 8)
    monkeypatch.setattr(P, "agora", lambda: datetime(2026, 10, 8, 14, 0))
    tarefas.criar("hoje estudar duration", datetime(2026, 10, 8, 8, 0, tzinfo=tarefas._agora().tzinfo))
    tarefas.criar("hoje ligar para o CLI-012", datetime(2026, 10, 8, 8, 0, tzinfo=tarefas._agora().tzinfo))
    assert diario.atualizar(dia)
    arq = P.pasta() / diario.caminho_rel(dia)
    texto = arq.read_text(encoding="utf-8")
    assert "# Quinta, 08/10/2026" in texto and "[[2026-10-07]]" in texto and "estudar duration" in texto.lower()
    assert "CLI-012" not in texto and "1 tarefa(s) de clientes" in texto
    arq.write_text(texto.replace("## Minhas anotações\n", "## Minhas anotações\nHoje entendi convexidade.\n"), encoding="utf-8")
    mtime = arq.stat().st_mtime_ns
    assert not diario.atualizar(dia) and arq.stat().st_mtime_ns == mtime  # nada mudou: não regrava
    tarefas.criar("hoje revisar FIIs", datetime(2026, 10, 8, 9, 0, tzinfo=tarefas._agora().tzinfo))
    assert diario.atualizar(dia)
    novo = arq.read_text(encoding="utf-8")
    assert "Hoje entendi convexidade." in novo and "revisar fiis" in novo.lower()
    # sem os marcadores (ele apagou), o bloco volta no fim sem apagar nada dele
    arq.write_text("# Meu dia\nsó meu texto\n", encoding="utf-8")
    diario.atualizar(dia)
    assert arq.read_text(encoding="utf-8").startswith("# Meu dia\nsó meu texto\n") and diario.INICIO in arq.read_text(encoding="utf-8")


def test_memoria_editada_no_obsidian_vale_na_proxima_conversa(tmp_path):
    from quiron.runtime.memoria_longa import MemoriaLonga

    m = MemoriaLonga()
    _, f1 = m.adicionar("prefere respostas curtas", "geral", 4, "dito")
    _, f2 = m.adicionar("estuda de manhã cedo", "geral", 3, "dito")
    nota = P.pasta() / P.ARQ_MEMORIA
    texto = nota.read_text(encoding="utf-8")
    assert texto.startswith("---\ntipo: memória") and f"[#{f1.id}] prefere respostas curtas" in texto
    texto = texto.replace(f"[#{f1.id}] prefere respostas curtas", f"[#{f1.id}] prefere respostas curtas e com números")
    texto = texto.replace(f"- [#{f2.id}] estuda de manhã cedo\n", "") + "- foca no CFP até junho\n"
    nota.write_text(texto, encoding="utf-8")
    mudancas = m.importar_edicoes_md()
    ativos = {f.texto for f in m.fatos()}
    assert "prefere respostas curtas e com números" in ativos and "foca no CFP até junho" in ativos
    assert "estuda de manhã cedo" not in ativos and mudancas
    # os dois espelhos ficam iguais e a próxima leitura não vê "edição"
    assert "foca no CFP até junho" in m.arquivo_md.read_text(encoding="utf-8") and m.importar_edicoes_md() == []
    # cópia da memória (LGPD/restauração) nunca escreve no Cérebro
    assert MemoriaLonga(tmp_path / "copia.db", arquivo_md=tmp_path / "M.md").arquivo_cerebro is None


def test_esquecer_cliente_limpa_o_cerebro():
    from quiron.servicos import lgpd

    _escrever("Minhas notas/Reunião.md", "Ideias gerais de alocação.\nCLI-012 quer previdência.\nCLI-0120 é outro.\n")
    _escrever("Minhas notas/Entrada/só cliente.md", "---\ntags: [cliente]\n---\nCLI-012 prefere WhatsApp #cliente\n")
    indice.atualizar(forcar=True)
    r = lgpd.esquecer_cliente("CLI-012")
    assert r.itens["linhas no Cérebro (notas do Obsidian)"] == 2
    assert (P.pasta() / "Minhas notas/Reunião.md").read_text(encoding="utf-8") == "Ideias gerais de alocação.\nCLI-0120 é outro.\n"
    assert not (P.pasta() / "Minhas notas/Entrada/só cliente.md").exists()
    assert indice.buscar("WhatsApp") == [] and indice.buscar("previdencia") == []
    with indice.conectar() as con:
        assert not [t for (t,) in con.execute("SELECT texto FROM notas") if "CLI-012\n" in (t or "") or "CLI-012 " in (t or "")]


def test_rotina_situacao_e_rotas():
    from quiron.runtime.roteamento import rotear

    r = rotina.ciclo()
    assert r["memoria"] == [] and (P.pasta() / diario.caminho_rel(P.agora().date())).exists()
    s = rotina.situacao()
    assert s["notas"] >= 5 and s["pasta"] == str(P.pasta().resolve())
    assert rotear("o que eu já estudei sobre duration?") == ("cerebro", "duration")
    assert rotear("o que anotei sobre previdência privada") == ("cerebro", "previdência privada")
    assert rotear("meu cérebro") == ("cerebro", "")
    assert rotear("anota que duration é sensibilidade") == ("nota", "duration é sensibilidade")


def test_bot_cerebro_sem_pergunta_responde_direto():
    import asyncio

    from quiron.runtime.organizacao_bot import OrganizacaoBot

    telas = asyncio.run(OrganizacaoBot().comando("cerebro", ""))
    assert "Cérebro:" in telas[0].texto and "Abrir pasta como cofre" in telas[0].texto


def test_terminal_busca_e_le_notas():
    from fastapi.testclient import TestClient

    from quiron.terminal.backend.app import app

    _escrever("Minhas notas/Duration.md", "Sensibilidade à taxa. [[Convexidade]]\n")
    _escrever("Minhas notas/Convexidade.md", "Curvatura. Volta para [[Duration]].\n")
    c = TestClient(app, base_url="http://127.0.0.1")
    d = c.get("/api/cerebro", params={"q": "sensibilidade"}).json()
    assert [n["titulo"] for n in d["notas"]] == ["Duration"] and d["situacao"]["minhas"] == 2
    n = c.get("/api/cerebro/nota", params={"c": "Minhas notas/Duration.md"}).json()
    assert n["cita"] == [{"titulo": "Convexidade", "caminho": "Minhas notas/Convexidade.md"}]
    assert n["citada_por"][0]["titulo"] == "Convexidade" and n["obsidian"].startswith("obsidian://open?vault=cerebro")
    assert c.get("/api/cerebro/nota", params={"c": "../../etc/passwd"}).status_code in (400, 404)
    assert c.get("/api/cerebro/nota", params={"c": "não existe"}).status_code == 404


def test_mcp_organizacao_tem_ferramentas_do_cerebro():
    from quiron.mcp.organizacao import servidor

    _escrever("Minhas notas/Duration.md", "Sensibilidade à taxa.\n")
    assert "[[Duration]]" in servidor.buscar_no_cerebro("sensibilidade")
    assert "Sensibilidade à taxa." in servidor.ler_nota("Duration")
    assert "Nada no Cérebro" in servidor.buscar_no_cerebro("inexistentezzz")
    assert os.path.basename(str(P.pasta())) == "cerebro"
