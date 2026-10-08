"""Fase 17 — conteúdo: insumos com fonte, pautas, peças revisadas (compliance, números, créditos, disclaimer), banco de
ideias e o fluxo no Telegram. Cérebro simulado, sem internet."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from quiron.nucleo import cerebro
from quiron.servicos.conteudo import gerador, ideias, insumos, revisao
from quiron.servicos.conteudo.insumos import Insumo


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


ITENS = [
    Insumo(1, "numero", "Selic meta: 13,75% a.a. (ref. 05/10/2026)", "Banco Central (SGS 432), 05/10/2026"),
    Insumo(2, "regra", "Regra da poupança: com a Selic acima de 8,5% a.a., rende 0,5% ao mês + TR (≈ 6,17% ao ano + TR)",
           "Lei 8.177/1991 com redação da Lei 12.703/2012", aviso="regra ainda não conferida"),
    Insumo(3, "noticia", "Manchete: Tesouro Direto amplia vendas em 2026", "Folha Mercado, 04/10/2026", "https://folha/x"),
    Insumo(4, "livro", "Trecho de livro: o juro composto…", "📚 Investimentos — Bodie, cap. 5"),
]


def _cerebro(respostas):
    fila = iter(respostas)
    return lambda p, **k: SimpleNamespace(texto=json.dumps(next(fila), ensure_ascii=False))


def test_regras_viram_insumos_com_contas_em_python(monkeypatch):
    from quiron.servicos.mercado import bcb
    from quiron.servicos.mercado.http import FonteIndisponivel

    def sem_rede(*a, **k):  # teste rápido não vai à internet (antes consultava o Banco Central de verdade: até 30 s)
        raise FonteIndisponivel("sem rede no teste")

    monkeypatch.setattr(bcb, "sgs", sem_rede)
    texto = dict(insumos.regras("Tesouro Selic ou poupança"))
    regra = next(t for t in texto if t.startswith("Regra da poupança"))
    assert "0,5% ao mês + TR (≈ 6,17% ao ano + TR)" in regra  # (1,005^12 − 1) = 6,17%
    assert any("até 180 dias: 22,5%" in t for t in texto) and any("R$ 250.000 por CPF" in t for t in texto)
    assert insumos.regras("bolsa americana") == []


def test_revisao_creditos_disclaimer_e_numeros():
    texto = "Com a Selic em 13,75% [1], a poupança rende 0,5% ao mês + TR [2]. Mas o CDB rende 15% ao ano."
    rev = revisao.revisar(texto, ITENS)
    assert "[1]" not in rev.texto and rev.creditos == ["Banco Central (SGS 432), 05/10/2026", "Lei 8.177/1991 com redação da Lei 12.703/2012"]
    assert rev.numeros_sem_fonte == ["15% "] or rev.numeros_sem_fonte == ["15%"]
    assert rev.avisos == ["regra ainda não conferida"]
    assert "não é recomendação" in rev.disclaimer and "Resolução CVM 20" not in rev.disclaimer and "inteligência artificial" in rev.disclaimer
    assert "Resolução CVM 20" in revisao.disclaimer("A PETR4 subiu.") and "Resolução CVM 20" not in revisao.disclaimer("Vale lembrar que…")
    final = rev.final("Título")
    assert final.startswith("RASCUNHO") and "Fontes: Banco Central" in final and "regra ainda não conferida" not in final
    assert "Números sem fonte" in rev.notas() and "regra ainda não conferida" in rev.notas()
    grave = revisao.revisar("Esse investimento é sem risco e rende garantido 2% ao mês.", ITENS)
    assert grave.graves and any("Negar o risco" in a for a in grave.alertas)
    assert revisao.formatar("Slide 1: a. Slide 2: b.").count("\n\nSlide") == 1


def test_pautas_com_ia_e_por_regras(monkeypatch):
    monkeypatch.setattr(cerebro, "perguntar", _cerebro([{"pautas": [
        {"titulo": "Poupança x Tesouro [1]", "gancho": "g", "angulo": "a", "formato": "reels", "por_que_agora": "Selic a 13,75% [1]", "fatos": [1, 2, 99]},
        {"titulo": "FGC", "gancho": "g", "angulo": "a", "formato": "tiktok", "por_que_agora": "p", "fatos": []}]}]))
    pautas, origem = gerador.gerar_pautas(itens=ITENS)
    assert origem == "ia" and pautas[0].titulo == "Poupança x Tesouro" and pautas[0].por_que_agora == "Selic a 13,75%"
    assert pautas[0].fontes == ["Banco Central (SGS 432), 05/10/2026", "Lei 8.177/1991 com redação da Lei 12.703/2012"]  # o fato 99 não existe
    assert pautas[1].formato == "carrossel"  # formato desconhecido → padrão
    monkeypatch.setattr(cerebro, "perguntar", lambda *a, **k: (_ for _ in ()).throw(cerebro.CerebroIndisponivel("x")))
    pautas, origem = gerador.gerar_pautas(itens=ITENS)
    assert origem == "regras" and "Tesouro Direto amplia vendas" in pautas[0].titulo and pautas[0].fontes == ["Folha Mercado, 04/10/2026"]


def test_peca_reescreve_quando_ha_problema_e_guarda_no_banco(monkeypatch, dados):
    ruim = {"titulo": "Poupança", "texto": "A poupança é sem risco e rende 9% ao ano [2]."}
    bom = {"titulo": "Poupança x Tesouro Selic", "texto": "1/3 Selic em 13,75% [1].\n\n2/3 Poupança: 0,5% ao mês + TR [2].\n\n3/3 Compare custos e prazos."}
    pedidos = []

    def falso(p, **k):
        pedidos.append(p)
        return SimpleNamespace(texto=json.dumps(ruim if len(pedidos) == 1 else bom, ensure_ascii=False))

    monkeypatch.setattr(cerebro, "perguntar", falso)
    peca = gerador.gerar_peca("Tesouro Selic ou poupança", "fio", itens=ITENS)
    assert peca.tentativas == 2 and "CORRIJA" in pedidos[1] and "número sem fonte: 9%" in pedidos[1]
    assert not peca.revisado.graves and peca.revisado.numeros_sem_fonte == []
    entrega = peca.entrega()
    assert entrega.startswith("RASCUNHO") and "Selic em 13,75%" in entrega and "[1]" not in entrega and "Fontes:" in entrega
    i = ideias.obter(peca.ideia)
    assert i.situacao == "rascunho" and i.formato == "fio" and (dados / "conteudo").exists()
    with pytest.raises(ValueError):
        gerador.gerar_peca("x", "tiktok", itens=ITENS)
    nova = ideias.criar("Por que a poupança perde para o Tesouro Selic")
    monkeypatch.setattr(cerebro, "perguntar", _cerebro([bom]))
    p2 = gerador.gerar_peca(f"#{nova.id}", "carrossel", itens=ITENS)
    assert p2.ideia == nova.id and ideias.obter(nova.id).situacao == "rascunho"


def test_banco_de_ideias():
    a = ideias.criar("Duration explicada com gangorra", "renda fixa sem medo")
    ideias.criar("Previdência PGBL x VGBL")
    assert [i.id for i in ideias.listar("gangorra")] == [a.id]
    assert ideias.atualizar(a.id, situacao="publicado").situacao == "publicado"
    assert [i.id for i in ideias.listar()] == [2]  # padrão: só ideias e rascunhos
    with pytest.raises(ValueError):
        ideias.atualizar(a.id, situacao="viral")
    with pytest.raises(ValueError):
        ideias.criar("x")


def test_telegram_conteudo(monkeypatch):
    from quiron.nucleo.config import Config
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    class SemMCP:
        ferramentas = []

        async def chamar(self, nome, args):
            return "ok"

    monkeypatch.setattr(insumos, "coletar", lambda tema="", com_livros=True: list(ITENS))
    monkeypatch.setattr(cerebro, "perguntar", _cerebro([
        {"pautas": [{"titulo": "Poupança x Tesouro", "gancho": "g", "angulo": "a", "formato": "reels", "por_que_agora": "p", "fatos": [1]}]},
        {"titulo": "Poupança x Tesouro", "texto": "Selic em 13,75% [1]. Compare custos."}]))
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    t = lambda x: asyncio.run(bot.tratar(111, 1, x))[0].texto  # noqa: E731
    assert "/pauta" in t("/ajuda")
    assert "1. Poupança x Tesouro [reels]" in t("/pauta juros")
    assert "Guardada: 💡 #1 Poupança x Tesouro" in t("/ideia salvar 1")
    assert t("/roteiro reels poupança").startswith("RASCUNHO")
    assert "formatos:" in t("/roteiro tiktok poupança")
    assert "#1" in t("/ideias") and "✅" in t("/ideia 1 publicado")
    assert "Negar o risco" in t("/conferir [poupança] Esse CDB é sem risco e rende muito bem para todos.")
