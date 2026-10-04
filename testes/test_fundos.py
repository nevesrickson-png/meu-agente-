"""Fase 10 — fundos com dados da CVM: base (cadastro, extrato, índice mensal, FII), métricas, pares e as análises.
Sem internet: uma "CVM de mentira" (arquivos no formato oficial) servida por httpx.MockTransport."""

import csv
import io
import zipfile
from datetime import date

import httpx
import numpy as np
import pandas as pd
import pytest

from quiron.servicos.fundos import cvm, metricas
from quiron.servicos.mercado import http

HOJE = date.today()
N_MESES = 26


def _meses() -> list[date]:
    inicio = date(HOJE.year, HOJE.month, 1)
    for _ in range(N_MESES):
        inicio = date(inicio.year - (inicio.month == 1), (inicio.month - 2) % 12 + 1, 1)
    return cvm.meses(inicio, HOJE)


MESES = _meses()
# CNPJ → (nome, taxa mensal, anbima, gestor, classe_cotas)
FUNDOS = {
    "11111111000111": ("ALFA MACRO FIC FIF MULTIMERCADO", 0.012, "Multimercados Macro", "ALFA GESTORA LTDA", "S"),
    "22222222000122": ("BETA MACRO FIF MULTIMERCADO", 0.006, "Multimercados Macro", "BETA ASSET LTDA", "N"),
    "33333333000133": ("ALFA PREVIDENCIA FIF MULTIMERCADO", 0.009, "Previdência Multimercado Livre", "ALFA GESTORA LTDA", "N"),
}
PARES = {f"9999999900{i:04d}": 0.004 + 0.001 * i for i in range(1, 8)}  # 7 pares: 0,5% a 1,1% ao mês


def _zip(arquivos: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, texto in arquivos.items():
            z.writestr(nome, texto.encode("latin-1"))
    return buf.getvalue()


def _csv(cab: list[str], linhas: list[list]) -> str:
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\n")
    w.writerow(cab)
    w.writerows(linhas)
    return out.getvalue()


def cota(taxa: float, k: int) -> float:
    return round(100 * (1 + taxa) ** k, 8)


def cadastro() -> bytes:
    fundos = [[str(i), c, "1", "2010-01-01", "2010-01-01", "FIF", n, "", "Em Funcionamento Normal", "", "", "", "", "0", "",
               "", "", "ADM", "PJ", c[:8] + "000100", g] for i, (c, (n, _, _, g, _)) in enumerate(FUNDOS.items())]
    fundos += [[str(100 + i), c, "1", "2010-01-01", "2010-01-01", "FIF", f"PAR {i} MACRO", "", "Em Funcionamento Normal", "",
                "", "", "", "0", "", "", "", "ADM", "PJ", "55555555000100", "OUTRA GESTORA"] for i, c in enumerate(PARES)]
    cab_f = ["ID_Registro_Fundo", "CNPJ_Fundo", "Codigo_CVM", "Data_Registro", "Data_Constituicao", "Tipo_Fundo",
             "Denominacao_Social", "Data_Cancelamento", "Situacao", "Data_Inicio_Situacao", "Data_Adaptacao_RCVM175",
             "Data_Inicio_Exercicio_Social", "Data_Fim_Exercicio_Social", "Patrimonio_Liquido", "Data_Patrimonio_Liquido",
             "Diretor", "CNPJ_Administrador", "Administrador", "Tipo_Pessoa_Gestor", "CPF_CNPJ_Gestor", "Gestor"]
    cab_c = ["ID_Registro_Fundo", "ID_Registro_Classe", "CNPJ_Classe", "Codigo_CVM", "Data_Registro", "Data_Constituicao",
             "Data_Inicio", "Tipo_Classe", "Denominacao_Social", "Situacao", "Data_Inicio_Situacao", "Classificacao",
             "Indicador_Desempenho", "Classe_Cotas", "Classificacao_Anbima", "Tributacao_Longo_Prazo", "Entidade_Investimento",
             "Permitido_Aplicacao_CemPorCento_Exterior", "Classe_ESG", "Forma_Condominio", "Exclusivo", "Publico_Alvo",
             "Patrimonio_Liquido", "Data_Patrimonio_Liquido", "CNPJ_Auditor", "Auditor", "CNPJ_Custodiante", "Custodiante",
             "CNPJ_Controlador", "Controlador"]

    def classe(idf, c, nome, anbima, cotas, pl):
        return [idf, f"C{idf}", c, "1", "2010-01-01", "2010-01-01", "2010-01-01", "Classes de Cotas de Fundos FIF", nome,
                "Em Funcionamento Normal", "", "Multimercado", "", cotas, anbima, "S", "", "", "N", "Aberto", "N",
                "Público Geral", pl, "2026-01-01", "", "", "", "", "", ""]

    classes = [classe(str(i), c, n, a, ct, "500000000.00") for i, (c, (n, _, a, _, ct)) in enumerate(FUNDOS.items())]
    classes += [classe(str(100 + i), c, f"PAR {i} MACRO", "Multimercados Macro", "N", "50000000.00")
                for i, c in enumerate(PARES)]
    return _zip({"registro_fundo.csv": _csv(cab_f, fundos), "registro_classe.csv": _csv(cab_c, classes),
                 "registro_subclasse.csv": _csv(["ID_Registro_Classe", "ID_Subclasse", "Codigo_CVM", "Data_Constituicao",
                                                 "Data_Inicio", "Denominacao_Social", "Situacao", "Data_Inicio_Situacao",
                                                 "Forma_Condominio", "Exclusivo", "Publico_Alvo", "Previdenciario",
                                                 "Exclusivo_INR", "Exclusivo_Previdencia_Complementar"], [])})


def extrato() -> str:
    cab = ["TP_FUNDO_CLASSE", "CNPJ_FUNDO_CLASSE", "DENOM_SOCIAL", "DT_COMPTC", "CLASSE_ANBIMA", "PUBLICO_ALVO", "APLIC_MIN",
           "QT_DIA_CONVERSAO_COTA", "QT_DIA_PAGTO_RESGATE", "TAXA_ADM", "TAXA_PERFM", "PARAM_TAXA_PERFM", "EXISTE_TAXA_SAIDA"]
    return _csv(cab, [["CLASSES - FIF", cvm.formatar_cnpj("11111111000111"), "ALFA", f"{HOJE.year}-01-10", "MACRO",
                       "PÚBLICO EM GERAL", "500.00", "30", "1", "2.000000", "20.000000", "CDI", "N"],
                      ["CLASSES - FIF", cvm.formatar_cnpj("11111111000111"), "ALFA", f"{HOJE.year}-02-10", "MACRO",
                       "PÚBLICO EM GERAL", "1000.00", "30", "1", "1.900000", "20.000000", "CDI", "N"]])


def diario(mes: date) -> bytes:
    k = MESES.index(mes) + 1
    cab = ["TP_FUNDO_CLASSE", "CNPJ_FUNDO_CLASSE", "ID_SUBCLASSE", "DT_COMPTC", "VL_TOTAL", "VL_QUOTA", "VL_PATRIM_LIQ",
           "CAPTC_DIA", "RESG_DIA", "NR_COTST"]
    linhas = []
    todos = {c: f[1] for c, f in FUNDOS.items()} | PARES
    ult_dia = min(28, HOJE.day) if mes == MESES[-1] else 28
    for c, taxa in todos.items():
        # dia 1 com a cota do mês anterior (não pode contar); último dia com a cota do mês
        linhas.append(["CLASSES - FIF", cvm.formatar_cnpj(c), "", f"{mes:%Y-%m}-01", "0", cota(taxa, k - 1), "1000000",
                       "100.00", "50.00", "10"])
        if ult_dia > 1:
            linhas.append(["CLASSES - FIF", cvm.formatar_cnpj(c), "", f"{mes:%Y-%m}-{ult_dia:02d}", "0", cota(taxa, k),
                           f"{50_000_000 + k * 1000}", "200.00", "0.00", str(10 + k)])
    return _zip({f"inf_diario_fi_{mes:%Y%m}.csv": _csv(cab, linhas)})


def fii_zip(ano: int) -> bytes:
    cab_g = ["Tipo_Fundo_Classe", "CNPJ_Fundo_Classe", "Data_Referencia", "Versao", "Nome_Fundo_Classe", "Codigo_ISIN",
             "Segmento_Atuacao", "Mandato", "Tipo_Gestao", "Publico_Alvo"]
    cab_c = ["CNPJ_Fundo_Classe", "Data_Referencia", "Versao", "Total_Numero_Cotistas", "Patrimonio_Liquido", "Cotas_Emitidas",
             "Valor_Patrimonial_Cotas", "Percentual_Despesas_Taxa_Administracao", "Percentual_Rentabilidade_Efetiva_Mes",
             "Percentual_Rentabilidade_Patrimonial_Mes", "Percentual_Dividend_Yield_Mes"]
    g, c = [], []
    for m in range(1, 13):
        ref = f"{ano}-{m:02d}-01"
        for cnpj, isin, cotistas in (("77777777000177", "BRTEST" + "CTF000", 50000), ("88888888000188", "BRTESTCTF000", 3)):
            g.append(["Classe", cvm.formatar_cnpj(cnpj), ref, "1", f"FII {cnpj[:2]}", isin, "Logística", "Renda", "Ativa",
                      "INVESTIDORES EM GERAL"])
            c.append([cvm.formatar_cnpj(cnpj), ref, "1", cotistas, "1000000000", "10000000", "100", "0.0008", "0.01", "0.002",
                      "0.008"])
    return _zip({f"inf_mensal_fii_geral_{ano}.csv": _csv(cab_g, g), f"inf_mensal_fii_complemento_{ano}.csv": _csv(cab_c, c)})


def responder(req: httpx.Request) -> httpx.Response:
    caminho = req.url.path
    nome = caminho.rsplit("/", 1)[-1]
    if nome == "registro_fundo_classe.zip":
        return httpx.Response(200, content=cadastro())
    if nome.startswith("extrato_fi_"):
        return httpx.Response(200, content=extrato().encode("latin-1")) if str(HOJE.year) in nome else httpx.Response(404)
    if nome.startswith("inf_diario_fi_"):
        aaaamm = nome[14:20]
        mes = date(int(aaaamm[:4]), int(aaaamm[4:]), 1)
        return httpx.Response(200, content=diario(mes)) if mes in MESES else httpx.Response(404)
    if nome.startswith("inf_mensal_fii_"):
        return httpx.Response(200, content=fii_zip(int(nome[15:19])))
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def cvm_falsa(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(responder)))
    yield
    http.definir_cliente(None)


def bench() -> pd.DataFrame:
    idx = pd.period_range(MESES[0], MESES[-1], freq="M")
    g = np.random.default_rng(1)
    return pd.DataFrame({"CDI": 0.008, "IBOV": g.normal(0.01, 0.05, len(idx))}, index=idx)


# ---------------------------------------------------------------- base
def test_cadastro_extrato_busca_e_indice_mensal():
    cvm.atualizar_cadastro()
    achados = cvm.buscar("alfa macro")
    assert [a.cnpj for a in achados] == ["11111111000111"] and achados[0].gestor == "ALFA GESTORA LTDA"
    assert cvm.buscar("11.111.111/0001-11")[0].nome.startswith("ALFA")
    assert cvm.extrato("11111111000111")["taxa_adm"] == 1.9  # o extrato mais recente vence
    baixados = cvm.garantir_meses(N_MESES)
    assert len(baixados) == len(MESES)
    assert cvm.garantir_meses(N_MESES) == []  # nada de novo: meses fechados são finais e os recentes valem por 12 h
    linhas, sub = cvm.serie_mensal("11111111000111")
    assert sub == "" and len(linhas) == len(MESES)
    primeiro = linhas[0]
    assert primeiro["cota"] == cota(0.012, 1) and primeiro["captacao"] == 300 and primeiro["resgate"] == 50
    assert primeiro["cotistas"] == 11
    classes, nomes = cvm.fundos_da_gestora("alfa gestora")
    assert nomes == ["ALFA GESTORA LTDA"] and len(classes) == 2


# ---------------------------------------------------------------- métricas
def test_rentabilidade_risco_e_pares_conferidos_a_mao():
    cvm.atualizar_cadastro()
    cvm.atualizar_extrato()
    cvm.garantir_meses(N_MESES)
    a = metricas.analisar("22222222000122", bench())
    j = {x.nome: x for x in a.janelas}
    fechados = len(MESES) - 1  # o mês corrente fica fora
    assert j["12 meses"].retorno == pytest.approx(cota(0.006, fechados) / cota(0.006, fechados - 12) - 1)
    assert j["12 meses"].cdi == pytest.approx(1.008 ** 12 - 1)
    assert j["12 meses"].pct_cdi == pytest.approx((1.006 ** 12 - 1) / (1.008 ** 12 - 1), rel=1e-6)
    assert j["36 meses"].retorno is None  # histórico curto
    assert a.risco.vol_aa == pytest.approx(0, abs=1e-6) and a.risco.max_drawdown == 0 and a.risco.acima_cdi == 0
    # pares: 7 pares de 0,5% a 1,1% ao mês + o ALFA (FIC, 1,2%); o BETA (0,6%) só supera o par de 0,5%
    pct, n = a.percentis["12 meses"]
    assert n == 8 and pct == pytest.approx(100 * 1 / 8)
    assert a.captacao_liquida_12m == pytest.approx(12 * 250)


# ---------------------------------------------------------------- análises
def test_comparativo_gestora_previdencia_e_fii(tmp_path):
    from quiron.servicos.analise.fila import carregar_tipos
    from quiron.servicos.analise.tipos import fundos as t

    assert {"fundo_analise", "fundos_comparativo", "gestora", "previdencia_portabilidade", "fii_comparativo"} <= set(carregar_tipos())
    rel = t.comparativo({"cnpjs": ["11111111000111", "beta macro"], "anos": 2}, dados_bench=bench(), redigir=False)
    assert [f["cnpj"] for f in rel.fatos["fundos"]] == ["11.111.111/0001-11", "22.222.222/0001-22"]
    assert rel.fatos["fundos"][0]["taxa_adm_pct"] == 1.9 and rel.fatos["fundos"][0]["resgate"] == "D+30+1"
    conf = next(tb for s in rel.secoes for tb in s.tabelas if tb.titulo.startswith("Conferência"))
    fechados = len(MESES) - 1
    linha = conf.linhas[0]
    assert linha[3] == round(cota(0.012, fechados - 12), 8) and linha[5] == round(cota(0.012, fechados), 8)
    assert rel.salvar(tmp_path / "rel")["pdf"].stat().st_size > 20_000
    with pytest.raises(ValueError):
        t.comparativo({"cnpjs": ["11111111000111"]}, dados_bench=bench(), redigir=False)
    um = t.fundo({"cnpj": "33333333000133"}, dados_bench=bench(), redigir=False)
    assert um.tipo == "fundo_analise"

    g = t.gestora({"gestora": "alfa gestora"}, dados_bench=bench(), redigir=False)
    assert g.fatos["classes"] == 2 and g.fatos["pl_sem_fic"] == 500_000_000  # o FIC fica fora do patrimônio

    p = t.previdencia({"cnpj_atual": "33333333000133", "cnpj_destino": "22222222000122", "saldo": 100_000, "anos": 10,
                       "renda_mensal_aposentadoria": 8_000}, dados_bench=bench(), redigir=False)
    ra = (1.009 ** 12) - 1
    assert p.fatos["retorno_anual_atual_pct"] == pytest.approx(ra * 100, abs=0.01)
    assert p.fatos["projecao"][0]["saldo_final"] == pytest.approx(100_000 * (1 + ra) ** 10, rel=1e-6)
    assert p.fatos["diferenca_projetada"] < 0

    f = t.fii_comparativo({"fiis": "TEST11"}, precos={"TEST11": 80.0}, proventos={"TEST11": 9.6}, redigir=False)
    fii = f.fatos["fiis"][0]
    assert fii["vp_cota"] == 100 and fii["p_vp"] == 0.8 and fii["dy_12m_sobre_preco_pct"] == pytest.approx(12.0)
    assert fii["dy_12m_sobre_vp_pct"] == pytest.approx(9.6) and fii["cotistas"] == 50000  # ISIN repetido: o de mais cotistas
    sem = t.fii_comparativo({"fiis": ["TEST11"]}, precos={"TEST11": 80.0}, proventos={}, redigir=False)
    assert sem.fatos["fiis"][0]["dy_12m_sobre_preco_pct"] == pytest.approx(12 * 0.8 / 80 * 100)  # declarado à CVM
