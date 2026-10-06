"""Resumo de mercado escrito, correções vistas no Telegram, perfil de empresa e imóveis de FII — sem internet."""

import asyncio
import io
import zipfile
from datetime import date, datetime, timedelta

import pytest

from quiron.nucleo import cerebro
from quiron.servicos.mercado import bcb, cotacoes, resumo, tesouro
from quiron.servicos.mercado.http import FonteIndisponivel


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def _serie(inicio=100.0, passo=0.1, dias=370, fim=datetime(2026, 10, 6), pular: set[date] | None = None):
    saida, v = [], inicio
    for i in range(dias, -1, -1):
        d = fim - timedelta(days=i)
        if d.weekday() >= 5 or (pular and d.date() in pular):
            continue
        v += passo
        saida.append((d, round(v, 4)))
    return saida


# ---------------------------------------------------------------- desempenho (variação semanal/mensal do TRXF11)
def test_desempenho_semana_mes_ano():
    s = _serie()
    d = cotacoes.desempenho("TRXF11", s)
    assert d["ultimo"] == s[-1][1] and d["anterior"] == s[-2][1]
    assert d["semana"] > 0 and d["mes"] > d["semana"] and d["ano"] > d["mes"] and d["doze_meses"] > d["ano"]
    assert d["minima_52s"] == s[0][1] and d["maxima_52s"] == s[-1][1]
    with pytest.raises(FonteIndisponivel):
        cotacoes.desempenho("X", s[:1])


# ---------------------------------------------------------------- resumo de mercado
def _sem_rede(monkeypatch, texto_ia: str | None):
    ibov = _serie(180000, 80)
    monkeypatch.setattr(cotacoes, "historico", lambda a, p="1y": ibov if a in {"IBOV", "SMLL"} else
                        (_serie(4.0, 0.001) if a.startswith("^T") else (_ for _ in ()).throw(FonteIndisponivel("sem"))))
    monkeypatch.setattr(cotacoes, "cotacao", lambda a: (_ for _ in ()).throw(FonteIndisponivel("sem")))
    ponto = bcb.Ponto(date(2026, 10, 6), 13.75)
    monkeypatch.setattr(bcb, "sgs", lambda k, n=2: bcb.Serie(k, k, "%", [bcb.Ponto(date(2026, 10, 5), 13.75), ponto], "BC", datetime.now(), False))
    monkeypatch.setattr(bcb, "focus", lambda i, a=None: bcb.Expectativa(i, a or 2026, 13.5, 13.75, date(2026, 10, 2), 100, "BC", datetime.now()))
    monkeypatch.setattr(tesouro, "titulos_atuais", lambda: (_ for _ in ()).throw(FonteIndisponivel("sem")))
    monkeypatch.setattr(resumo, "_manchetes", lambda horas=24: {"bolsa": ["Ibovespa renova máxima aos 209,5 mil pontos (Valor, InfoMoney)"]})
    monkeypatch.setattr("quiron.servicos.mercado.briefing.eventos_agenda", lambda h, d=6: [])

    def perguntar(*a, **k):
        if texto_ia is None:
            raise cerebro.CerebroIndisponivel("sem IA")
        return cerebro.Resposta(texto_ia, "simulado", [])

    monkeypatch.setattr(cerebro, "perguntar", perguntar)


def test_resumo_com_ia_tira_numero_inventado(monkeypatch):
    texto = ("RESUMO EXECUTIVO: O Ibovespa renovou máxima aos 209,5 mil pontos. O dólar caiu 3,33% hoje.\n"
             "### bolsa_br\nO Ibovespa renovou máxima aos 209,5 mil pontos, com bancos em alta. Analistas veem 250 mil pontos. "
             "Leitura prática: cautela com a euforia.\n### juros\nA Selic segue em 13,75%. Leitura prática: CDI ainda paga bem.\n")
    _sem_rede(monkeypatch, texto)
    r = resumo.gerar(datetime(2026, 10, 6, 8, 0, tzinfo=resumo.BRT))
    assert r.redigido_por_ia and "209,5 mil" in r.executivo and "3,33" not in r.executivo  # número sem fonte saiu
    bolsa = next(b for b in r.blocos if b.chave == "bolsa_br")
    assert "250 mil" not in bolsa.texto and "**Leitura prática:** cautela" in bolsa.texto
    cripto = next(b for b in r.blocos if b.chave == "cripto")
    assert cripto.texto == "Sem destaque relevante hoje."  # sem dado nem IA para a seção
    moedas = next(b for b in r.blocos if b.chave == "moedas")
    assert "Dólar PTAX (Banco Central)" in moedas.texto  # a IA não escreveu: os fatos entram em tópicos
    assert (r.pasta / "relatorio.pdf").exists() and (r.pasta / "resumo-de-mercado-2026-10-06.pdf").exists()
    assert resumo.ultimo()["texto"].startswith("📰 **Resumo de Mercado — 06/10/2026**")


def test_resumo_sem_ia_sai_em_topicos(monkeypatch):
    _sem_rede(monkeypatch, None)
    r = resumo.gerar(datetime(2026, 10, 6, 8, 0, tzinfo=resumo.BRT), salvar=False)
    assert not r.redigido_por_ia and not r.executivo
    juros = next(b for b in r.blocos if b.chave == "juros")
    assert "• Selic meta: 13,75% a.a." in juros.texto and "Focus" in juros.texto
    assert "Yahoo Finance (fechamentos)" in r.fontes


def test_variacao_do_dia_nao_mistura_pregoes():
    ref = _serie(180000, 80)
    feriado_falso = {date(2026, 10, 5)}
    sem_dia = _serie(100, 0.1, pular=feriado_falso)  # fonte pulou o pregão de 05/10 (como o SMAL11 no Yahoo)
    assert not resumo._dia_confiavel("SMLL", sem_dia, ref)
    assert resumo._dia_confiavel("SMLL", _serie(100, 0.1), ref)
    assert not resumo._dia_confiavel("USDBRL", _serie(5, 0.001), ref)  # câmbio: o dia vem da PTAX


# ---------------------------------------------------------------- correções do Telegram
def test_relatorio_grava_sem_arquivo_temporario(tmp_path):
    from quiron.servicos.analise.relatorio import Relatorio, Secao

    rel = Relatorio("Teste", "teste", resumo=["ok"], secoes=[Secao("A", "texto")])
    caminhos = rel.salvar(tmp_path / "r")
    assert caminhos["pdf"].read_bytes()[:4] == b"%PDF" and not list((tmp_path / "r").glob("*.tmp*"))


def test_analise_com_erro_volta_para_a_fila_e_motivo_amigavel(tmp_path):
    from quiron.servicos.analise import fila as mod

    f = mod.Fila(tmp_path / "a.db", tmp_path / "rel")
    t = f.pedir("renda_fixa_comparativo", {}, origem="telegram")
    with f._con() as c:
        c.execute("UPDATE tarefas SET situacao='erro', erro=?, entregue=1 WHERE id=?",
                  ("PermissionError: [WinError 5] Acesso negado: 'relatorio.tmp.pdf'", t.id))
    assert "Windows não deixou gravar" in mod.motivo_amigavel(f.obter(t.id).erro)
    assert f.repetir(t.id).situacao == "na fila" and f.repetir(t.id) is None  # só repete o que está com erro
    assert "fonte de dados não respondeu" in mod.motivo_amigavel("ConnectError: x")


def test_resposta_so_com_sugestoes_vira_botoes():
    from quiron.runtime.telegram_bot import BotQuiron, Saida

    bot = BotQuiron.__new__(BotQuiron)
    bot.sugestoes = {}
    s = bot.com_sugestoes([Saida("» Ver briefing\n» Consultar cotações")])[0]
    assert "»" not in s.texto and len(s.linhas) == 2 and s.texto == "Escolha o próximo passo:"


def test_rotas_novas():
    from quiron.runtime.roteamento import rotear

    assert rotear("resumo de mercado") == ("resumo", "")
    assert rotear("Faça o resumo de mercado.") == ("resumo", "")
    assert rotear("resumo do mercado de câmbio da semana passada") is None


# ---------------------------------------------------------------- perfil da empresa (FCA/FRE)
def _zip(arquivos: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo.encode("latin-1"))
    return buf.getvalue()


def test_perfil_da_empresa_sem_documentos_pessoais(monkeypatch, tmp_path):
    from quiron.servicos.valuation import cvm_cias, perfil

    ano = date.today().year
    fca = _zip({
        f"fca_cia_aberta_geral_{ano}.csv": "CNPJ_Companhia;Versao;Setor_Atividade;Descricao_Atividade;Data_Constituicao;"
        "Especie_Controle_Acionario;Pagina_Web\n84.429.695/0001-11;1;Máquinas;Holding do Grupo WEG;1961-06-30;Privado Holding;ri.weg.net\n",
        f"fca_cia_aberta_endereco_{ano}.csv": "CNPJ_Companhia;Tipo_Endereco;Cidade;Sigla_UF\n84.429.695/0001-11;Endereço da Sede;Jaraguá do Sul;SC\n"})
    fre = _zip({
        f"fre_cia_aberta_posicao_acionaria_{ano}.csv": "CNPJ_Companhia;Versao;Acionista;CPF_CNPJ_Acionista;ID_Acionista_Relacionado;"
        "Percentual_Total_Acoes_Circulacao;Percentual_Acao_Ordinaria_Circulacao;Acionista_Controlador\n"
        "84.429.695/0001-11;3;WPA Participações;11.111.111/0001-11;;50.09;50.09;S\n"
        "84.429.695/0001-11;3;Fulano de Tal;123.456.789-00;;0.2;0.2;S\n"
        "84.429.695/0001-11;3;Holding do Fulano;22.222.222/0001-22;8228535;100;100;S\n"
        "84.429.695/0001-11;2;Versão antiga;33.333.333/0001-33;;60;60;S\n",
        f"fre_cia_aberta_participacao_sociedade_{ano}.csv": "CNPJ_Companhia;Versao;Razao_Social;Tipo_Sociedade;Descricao_Atividades;"
        "Pais_Sede;UF_Sede;Municipio_Sede;Participacao_Emissor\n84.429.695/0001-11;3;WEG Equipamentos;Controlada;Motores;Brasil;SC;Jaraguá do Sul;100\n",
        f"fre_cia_aberta_empregado_posicao_local_{ano}.csv": "CNPJ_Companhia;Versao;Quantidade_Norte;Quantidade_Nordeste;"
        "Quantidade_Centro_Oeste;Quantidade_Sudeste;Quantidade_Sul;Quantidade_Exterior\n84.429.695/0001-11;3;8;0;0;227;994;1406\n"})
    zips = {"fca": tmp_path / "fca.zip", "fre": tmp_path / "fre.zip"}
    zips["fca"].write_bytes(fca)
    zips["fre"].write_bytes(fre)
    monkeypatch.setattr(cvm_cias, "arquivo", lambda doc, a: zips.get(doc) if a == ano else None)
    monkeypatch.setattr(perfil, "_yahoo", lambda t: {"setor": "Industrials", "industria": "Electrical Equipment", "funcionarios": 49258,
                                                     "negocio_original": "WEG produces electric motors."})
    monkeypatch.setattr(perfil, "_traduzir", lambda t, c=None: "A WEG produz motores elétricos.")
    e = cvm_cias.Empresa("84429695000111", "5410", "WEG S.A.", "Máquinas", "Holding do Grupo WEG", ["WEGE3"])
    p = perfil.perfil(e)
    assert p.sede == "Jaraguá do Sul, SC" and p.negocio == "A WEG produz motores elétricos." and p.funcionarios == 49258
    assert [a["nome"] for a in p.acionistas] == ["WPA Participações"]  # < 5% e cadeia societária ficam de fora
    assert p.empregados_regiao == {"Norte": 8, "Sudeste": 227, "Sul": 994, "Exterior": 1406}
    t = perfil.texto(p)
    assert "123.456.789" not in t and "11.111.111" not in t and "WPA Participações 50,09% (controlador)" in t
    sec = perfil.secao(p)
    assert sec.titulo == "Perfil e atividades" and len(sec.tabelas) == 4
    assert perfil.perfil(e).nome == "WEG S.A."  # do cache


# ---------------------------------------------------------------- imóveis de FII (informe trimestral)
def test_local_do_imovel():
    from quiron.servicos.fundos.fii_imoveis import local

    assert local("Av. Ayrton Senna, 3000 - Barra da Tijuca, Rio de Janeiro - RJ") == ("Rio de Janeiro", "RJ")
    assert local("Rodovia Anhanguera, km 25, Cajamar/SP") == ("Cajamar", "SP")
    assert local("Rua X, 100, São Paulo, SP, CEP 01000-000") == ("São Paulo", "SP")
    assert local("Galpão em Betim") == ("", "")


def test_imoveis_do_fii(monkeypatch, tmp_path):
    from quiron.servicos.fundos import cvm, fii_imoveis

    ano = date.today().year
    cab = ("CNPJ_Fundo_Classe;Data_Referencia;Versao;Classe;Nome_Imovel;Endereco;Area;Numero_Unidades;Percentual_Vacancia;"
           "Percentual_Inadimplencia;Percentual_Receitas_FII;Percentual_Locado\n")
    imoveis = cab + (f"11.728.688/0001-47;{ano}-03-31;1;Imóveis para renda acabados;Antigo;Rua A - Cajamar - SP;1000;1;0;0;0.5;1\n"
                     f"11.728.688/0001-47;{ano}-06-30;1;Imóveis para renda acabados;Vinhedo;Rod. X, Vinhedo - SP;3000;1;0.1;0;0.6;0.9\n"
                     f"11.728.688/0001-47;{ano}-06-30;1;Imóveis para renda acabados;Betim;Av. Y - Betim - MG;1000;1;0;0;0.4;1\n")
    inq = ("CNPJ_Fundo_Classe;Data_Referencia;Versao;Nome_Imovel;Setor_Atuacao;Percentual_Receita_Imovel;Percentual_Receitas_FII\n"
           f"11.728.688/0001-47;{ano}-06-30;1;Vinhedo;E-commerce;1;0.6\n")
    ativo = ("CNPJ_Fundo_Classe;Data_Referencia;Versao;Tipo;Emissor;CNPJ_Emissor;Emissao;Serie;Codigo_Acao;Nome_Ativo;Data_Vencimento;"
             f"Quantidade;Valor\n22.222.222/0001-22;{ano}-06-30;1;CRI/CRA;Securitizadora;1;;;;CRI Logístico;2030-01-01;1;5000000\n")
    z = _zip({f"inf_trimestral_fii_imovel_{ano}.csv": imoveis, f"inf_trimestral_fii_imovel_renda_acabado_inquilino_{ano}.csv": inq,
              f"inf_trimestral_fii_ativo_{ano}.csv": ativo})

    def baixar(url):
        if str(ano) not in url:
            return None
        arq = tmp_path / f"t{ano}.zip"
        arq.write_bytes(z)
        return arq

    monkeypatch.setattr(cvm, "baixar", baixar)
    c = fii_imoveis.carteira("11.728.688/0001-47")
    assert [i["nome"] for i in c["imoveis"]] == ["Vinhedo", "Betim"]  # só o último trimestre
    assert c["area_total"] == 4000 and round(c["vacancia_ponderada"], 3) == 0.075
    assert list(c["por_uf"]) == ["SP", "MG"] and c["setores_inquilinos"] == {"E-commerce": 0.6}
    papel = fii_imoveis.carteira("22.222.222/0001-22")
    assert not papel["imoveis"] and papel["ativos_por_tipo"] == {"CRI/CRA": 5000000.0}
    sec = fii_imoveis.secoes("HGLG11", c)
    assert sec.titulo == "Imóveis e carteira — HGLG11" and "vacância média ponderada pela área de 7,5%" in sec.texto
    assert "Vinhedo — Vinhedo/SP" in fii_imoveis.texto("HGLG11", c)
