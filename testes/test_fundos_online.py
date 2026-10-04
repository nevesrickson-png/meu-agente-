"""Aceite da Fase 10 (online): o comparativo de 3 fundos reais bate com os arquivos brutos da CVM."""

import csv
import io
import zipfile

import pytest

from quiron.servicos.fundos import cvm
from quiron.servicos.mercado import http

pytestmark = pytest.mark.online
FUNDOS = ["22.215.116/0001-80", "30.566.221/0001-92", "12.124.089/0001-87"]  # Verde 30, Legacy Advisory, Ibiuna Hedge


def test_comparativo_de_3_fundos_reais_bate_com_a_cvm(tmp_path, monkeypatch):
    from quiron.servicos.analise.tipos.fundos import comparativo

    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    rel = comparativo({"cnpjs": FUNDOS, "anos": 1}, redigir=False)
    conf = next(t for s in rel.secoes for t in s.tabelas if t.titulo.startswith("Conferência"))
    for nome, janela, data_ini, cota_ini, data_fim, cota_fim, rent in conf.linhas:
        assert rent == pytest.approx((cota_fim / cota_ini - 1) * 100, abs=1e-4)
    # confere as cotas finais direto no arquivo bruto do informe diário da CVM (sem o código do Quíron)
    data_fim = conf.linhas[0][4]
    d, m, a = data_fim.split("/")
    r = http.cliente().get(cvm.URL_DIARIO.format(aaaamm=f"{a}{m}"), timeout=300)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        brutos = {(l["CNPJ_FUNDO_CLASSE"], l["DT_COMPTC"]): float(l["VL_QUOTA"])
                  for l in csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1"), delimiter=";")
                  if l["CNPJ_FUNDO_CLASSE"] in FUNDOS and not l.get("ID_SUBCLASSE")}
    for f, linha in zip(rel.fatos["fundos"], [l for l in conf.linhas if l[1] == "12 meses"]):
        assert brutos[(f["cnpj"], f"{a}-{m}-{d}")] == pytest.approx(linha[5], abs=1e-8)
