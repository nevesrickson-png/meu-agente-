"""Aceite da Fase 11 (online): DCF de empresa real (WEGE3) com premissas rastreáveis e dados que batem com a CVM."""

import csv
import io
import zipfile

import pytest

pytestmark = pytest.mark.online


def test_dcf_de_empresa_real_com_premissas_rastreaveis(tmp_path, monkeypatch):
    from quiron.servicos.analise.tipos.valuation import valuation_dcf
    from quiron.servicos.mercado import http

    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    rel = valuation_dcf({"empresa": "WEGE3"}, redigir=False)
    hist = next(t for s in rel.secoes for t in s.tabelas if t.titulo.startswith("Histórico"))
    ano, receita_mi = hist.linhas[-2][0], hist.linhas[-2][1]  # último ano fechado
    # confere a receita direto no arquivo bruto da DFP na CVM (sem o código do Quíron)
    r = http.cliente().get(f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip", timeout=300)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        nome = f"dfp_cia_aberta_DRE_con_{ano}.csv"
        bruto = [l for l in csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin-1"), delimiter=";")
                 if l["CNPJ_CIA"] == "84.429.695/0001-11" and l["CD_CONTA"] == "3.01" and l["ORDEM_EXERC"] == "ÚLTIMO"]
    assert receita_mi == pytest.approx(float(bruto[-1]["VL_CONTA"]) / 1000, abs=0.1)
    # toda linha do custo de capital tem fonte ou conta; toda premissa e fonte está escrita
    wacc = next(t for s in rel.secoes for t in s.tabelas if t.titulo.startswith("Custo de capital"))
    assert all(l[2] for l in wacc.linhas)
    assert any("Damodaran" in f for f in rel.fontes) and any("Focus" in f for f in rel.fontes) and any("^TNX" in f for f in rel.fontes)
    assert len(rel.premissas) >= 5 and "Uso interno" in rel.rodape
    assert 0.05 < rel.fatos["wacc_pct"] / 100 < 0.25 and rel.fatos["valor_por_acao_base"] > 0
