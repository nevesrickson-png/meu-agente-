from datetime import date

from quiron.nucleo import regras
from quiron.nucleo.config import ler_yaml
from quiron.nucleo.persona import gerar_persona, gravar_persona


def test_regras_de_mercado_carregam_e_tem_blocos_essenciais():
    r = regras.carregar_regras()
    for bloco in ("renda_fixa", "fundos", "renda_variavel", "previdencia", "fgc", "itcmd"):
        assert bloco in r and "verificado_em" in r[bloco], bloco
    faixas = r["renda_fixa"]["ir_tabela_regressiva"]
    assert [f["aliquota"] for f in faixas] == [0.225, 0.20, 0.175, 0.15]


def test_aviso_de_verificacao():
    hoje = date(2026, 10, 3)
    dados = {
        "a": {"verificado_em": None},
        "b": {"verificado_em": "2026-09-01"},
        "c": {"verificado_em": date(2026, 6, 1)},
    }
    s = {x.bloco: x for x in regras.situacao(dados, hoje)}
    assert not s["a"].ok and "NÃO verificado" in s["a"].aviso
    assert s["b"].ok and s["b"].dias == 32
    assert not s["c"].ok and "124 dias" in s["c"].aviso
    assert len(regras.avisos(dados, hoje)) == 2


def test_persona_gerada_do_yaml(tmp_path):
    dados = ler_yaml("persona")
    texto = gerar_persona(dados)
    assert texto.startswith("# Persona — Quíron")
    assert "No máximo **3 por dia**" in texto
    assert "contestar" in texto and "RASCUNHO" in texto
    destino = gravar_persona(tmp_path / "persona.md")
    assert destino.read_text(encoding="utf-8") == texto


def test_persona_commitada_esta_atualizada():
    from quiron.nucleo.config import PASTA_AGENTE

    atual = (PASTA_AGENTE / "persona.md").read_text(encoding="utf-8")
    assert atual == gerar_persona(ler_yaml("persona")), "rode: uv run quiron-gerar-persona"
