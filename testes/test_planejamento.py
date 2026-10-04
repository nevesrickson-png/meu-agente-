"""Fase 9 — planejamento financeiro (padrão CFP): ficha, tributos, diagnóstico, aposentadoria, sucessão, proteção,
PF × PJ, plano completo, LGPD e o MCP quiron-assessoria. Contas conferíveis à mão; sem internet."""

import asyncio
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from quiron.servicos.planejamento import aposentadoria, diagnostico, empresario, ficha, impostos, protecao, sucessao, tributario
from quiron.servicos.planejamento.ficha import Empresa, Ficha, FichaInvalida

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def cliente(**extra) -> dict:
    base = {
        "cliente": "CLI-101", "idade": 45, "uf": "SP", "estado_civil": "casado", "regime_bens": "comunhao_parcial",
        "idade_conjuge": 43, "dependentes": [{"relacao": "filha", "idade": 12}, {"relacao": "filho", "idade": 9}],
        "ocupacao": "clt", "renda_mensal_bruta": 20_000, "renda_conjuge_mensal": 9_000, "despesas_mensais": 18_000,
        "inss_beneficio_mensal": 3_000, "idade_inss": 65,
        "patrimonio": [{"nome": "Residência", "tipo": "residencia", "valor": 1_000_000},
                       {"nome": "Apartamento herdado", "tipo": "imovel", "valor": 400_000, "particular": True},
                       {"nome": "Investimentos", "tipo": "investimento", "valor": 600_000},
                       {"nome": "VGBL", "tipo": "previdencia_vgbl", "valor": 100_000}],
        "dividas": [{"nome": "Cheque especial", "saldo": 10_000, "parcela_mensal": 1_000, "taxa_am": 8.0}],
        "seguros": [{"tipo": "vida", "cobertura": 300_000}],
        "aporte_mensal": 3_000, "objetivos": [{"nome": "Faculdade", "valor": 200_000, "prazo_anos": 8, "prioridade": 1}],
        "idade_aposentadoria": 60, "renda_desejada_aposentadoria": 15_000, "perfil": "moderado",
    }
    return {**base, **extra}


# ---------------------------------------------------------------- tributos
def test_irpf_inss_simples_presumido_conferidos_a_mao():
    assert impostos.irpf_mensal(4_000, com_reducao=False) == pytest.approx(4_000 * 0.225 - 675.49)
    assert impostos.irpf_mensal(4_000) == 0  # até R$ 5 mil: zerado pela redução de 2026
    assert impostos.irpf_mensal(6_000) == pytest.approx(6_000 * 0.275 - 908.73 - (978.62 - 0.133145 * 6_000))
    assert impostos.irpf_mensal(10_000) == pytest.approx(10_000 * 0.275 - 908.73)  # acima de R$ 7.350: sem redução
    assert impostos.inss_empregado(3_000) == pytest.approx(1518 * 0.075 + (2793.88 - 1518) * 0.09 + (3000 - 2793.88) * 0.12)
    teto = 1518 * 0.075 + (2793.88 - 1518) * 0.09 + (4190.83 - 2793.88) * 0.12 + (8157.41 - 4190.83) * 0.14
    assert impostos.inss_empregado(20_000) == pytest.approx(teto)
    assert impostos.simples_aliquota(600_000, "iii") == pytest.approx((600_000 * 0.135 - 17_640) / 600_000)
    assert impostos.simples_aliquota(600_000, "v") == pytest.approx((600_000 * 0.195 - 9_900) / 600_000)
    lp = impostos.lucro_presumido(600_000, 0.02)
    assert lp.total == pytest.approx(192_000 * 0.15 + 192_000 * 0.09 + 600_000 * (0.0065 + 0.03 + 0.02))
    assert impostos.lucro_presumido(1_200_000, 0.05).adicional == pytest.approx((384_000 - 240_000) * 0.10)
    assert impostos.irpf_minimo_alta_renda(900_000, 0) == pytest.approx(900_000 * 0.05)
    assert impostos.irpf_minimo_alta_renda(1_500_000, 100_000) == pytest.approx(150_000 - 100_000)
    assert impostos.irpf_minimo_alta_renda(500_000, 0) == 0


def test_matematica_financeira():
    assert diagnostico.vf(0, 1_000, 0.01, 12) == pytest.approx(12_682.50, abs=0.01)
    assert diagnostico.pmt_para(12_682.50, 0, 0.01, 12) == pytest.approx(1_000, abs=0.01)
    assert diagnostico.pmt_para(100, 1_000, 0.01, 12) == 0
    assert diagnostico.vp_renda(1_000, 0, 120) == 120_000
    assert diagnostico.taxa_mensal(12.6825) == pytest.approx(0.01, abs=1e-6)


# ---------------------------------------------------------------- ficha
def test_ficha_so_aceita_codigo_mescla_e_guarda_historico(dados):
    with pytest.raises(FichaInvalida):
        ficha.salvar({"cliente": "João da Silva", "idade": 40})
    f = ficha.salvar(cliente())
    assert f.cliente == "CLI-101" and f.patrimonio_total == 2_100_000 and f.investimentos == 700_000
    assert f.liquido == 600_000 and len(f.filhos) == 2 and f.casado and f.tem_13
    f2 = ficha.salvar({"cliente": "cli-101", "despesas_mensais": 19_000})
    assert f2.despesas_mensais == 19_000 and f2.renda_mensal_bruta == 20_000  # mesclou
    assert len(list((dados / "fichas" / "historico").glob("CLI-101-*.json"))) == 1
    assert ficha.salvar({"cliente": "CLI-101", "idade": 50}, substituir=True).renda_mensal_bruta == 0
    pend = ficha.carregar("CLI-101").validar()
    assert any("renda" in p for p in pend) and any("UF" in p for p in pend)
    assert "CLI-101" in ficha.descrever(ficha.carregar("CLI-101"))


# ---------------------------------------------------------------- diagnóstico
def test_diagnostico_renda_liquida_e_indicadores():
    f = Ficha.de_dict(cliente())
    d = diagnostico.diagnosticar(f)
    inss = impostos.inss_empregado(20_000)
    ir = impostos.irpf_mensal(20_000 - inss - 2 * 2275.08 / 12)
    titular = (20_000 - inss - ir) * 13.33 / 12
    conj = (9_000 - impostos.inss_empregado(9_000) - impostos.irpf_mensal(9_000 - impostos.inss_empregado(9_000))) * 13.33 / 12
    assert d.renda.liquida == pytest.approx(titular + conj)
    assert d.sobra == pytest.approx(d.renda.liquida - 18_000 - 1_000)
    assert d.reserva_meta == 6 * 19_000 and d.reserva_atual == 600_000
    assert any("Dívida cara" in a for a in d.alertas)
    o = d.objetivos[0]
    assert o.retorno_real == 4.5 and o.aporte_mensal == pytest.approx(diagnostico.pmt_para(200_000, 0, diagnostico.taxa_mensal(4.5), 96))


# ---------------------------------------------------------------- aposentadoria
def test_aposentadoria_capital_aporte_e_monte_carlo():
    f = Ficha.de_dict(cliente())
    p = {**diagnostico.premissas(), "simulacoes_monte_carlo": 800}
    a = aposentadoria.planejar(f, 500_000, p)
    i_u = diagnostico.taxa_mensal(3.0)
    # 15 mil/mês dos 60 aos 65 e (15 mil − 3 mil) dos 65 aos 95, a 3% real
    esperado = diagnostico.vp_renda(15_000, i_u, 60) + diagnostico.vp_renda(12_000, i_u, 360) / (1 + i_u) ** 60
    assert a.capital_necessario == pytest.approx(esperado)
    i_a = diagnostico.taxa_mensal(4.5)
    assert diagnostico.vf(500_000, a.aporte_necessario, i_a, 180) == pytest.approx(a.capital_necessario)
    assert a.capital_projetado == pytest.approx(diagnostico.vf(500_000, 3_000, i_a, 180))
    assert 0.3 < a.prob_sucesso_necessario < 0.65  # o aporte "médio" dá ~metade de chance
    assert a.aporte_alvo > a.aporte_necessario and a.renda_alvo < a.renda_sustentavel
    assert a.prob_sucesso_atual < a.prob_sucesso_necessario
    base = next(s for s in a.sensibilidade if s[0] == "Base")[1]
    assert next(s for s in a.sensibilidade if s[0] == "Aposentar 3 anos depois")[1] < base
    assert len(a.idades) == 95 - 45 + 1 and len(a.trajetoria["Trajetória atual"]) == len(a.idades)


# ---------------------------------------------------------------- sucessão e proteção
def test_sucessao_meacao_itcmd_e_liquidez_conferidos_a_mao():
    f = Ficha.de_dict(cliente())
    s = sucessao.planejar(f)
    # monte sem VGBL = 2,0 mi; meação = 50% dos bens comuns (1,6 mi) = 800 mil; herança 1,2 mi; dívida 10 mil
    assert s.monte == 2_000_000 and s.meacao == 800_000 and s.heranca == 1_200_000
    assert s.aliquota_itcmd == 0.04 and s.itcmd == pytest.approx((1_200_000 - 10_000) * 0.04)
    assert s.custos_inventario == pytest.approx(2_000_000 * 0.075)
    assert s.manutencao_familia == pytest.approx(18_000 * 12 * 0.70)
    assert s.liquidez_fora_inventario == 400_000
    assert s.falta_liquidez == pytest.approx(max(0, s.itcmd + s.custos_inventario + s.manutencao_familia - 400_000))
    rj = sucessao.planejar(Ficha.de_dict(cliente(uf="RJ", regime_bens="separacao_total")))
    assert rj.aliquota_itcmd == 0.08 and rj.meacao == 0 and "máxima" in rj.aliquota_texto


def test_protecao_metodo_das_necessidades():
    f = Ficha.de_dict(cliente())
    d = diagnostico.diagnosticar(f)
    s = sucessao.planejar(f)
    pr = protecao.planejar(f, d, s)
    conj = next(v for n, v in d.renda.detalhes if n.startswith("Cônjuge"))
    assert pr.anos_renda_familia == 24 - 9 and pr.renda_familia_mensal == pytest.approx(18_000 * 0.7 - conj)
    renda = diagnostico.vp_renda(pr.renda_familia_mensal, diagnostico.taxa_mensal(3.0), 15 * 12)
    total = renda + 10_000 + 2 * 200_000 + 15_000 + s.itcmd + s.custos_inventario
    assert pr.necessidade_vida == pytest.approx(total)
    assert pr.falta_vida == pytest.approx(max(0, total - 600_000 - 100_000 - 300_000))
    assert not pr.tem_saude and any("saúde" in n for n in pr.notas)


# ---------------------------------------------------------------- tributário e PF × PJ
def test_tributario_completa_simplificada_e_pgbl():
    f = Ficha.de_dict(cliente(renda_mensal_bruta=10_000, dependentes=[{"relacao": "filho", "idade": 5}], renda_conjuge_mensal=0))
    t = tributario.planejar(f)
    inss = impostos.inss_empregado(10_000) * 12
    assert t.rendimento_tributavel == 120_000
    assert t.simplificada.imposto == pytest.approx((120_000 - 16_754.34) * 0.275 - 908.73 * 12)
    assert t.completa.imposto == pytest.approx((120_000 - inss - 2_275.08) * 0.275 - 908.73 * 12)
    assert t.melhor == "Simplificada" and t.pgbl_limite == pytest.approx(14_400)
    com_pgbl = (120_000 - inss - 2_275.08 - 14_400) * 0.275 - 908.73 * 12
    assert t.pgbl_vale and t.pgbl_economia_adicional == pytest.approx(t.simplificada.imposto - com_pgbl)


def test_empresario_regimes_conferidos_a_mao():
    e = empresario.comparar(Empresa(faturamento_anual=600_000, despesas_anuais=90_000, folha_anual=60_000, iss=0.02,
                                    regime_atual="pf"))
    c = {x.nome: x for x in e.cenarios}
    iii, v, lp, pf = c["Simples — Anexo III (fator R)"], c["Simples — Anexo V"], c["Lucro Presumido"], c["Pessoa física (autônomo)"]
    assert iii.tributos_empresa == pytest.approx(600_000 * 0.135 - 17_640)
    assert iii.pro_labore == pytest.approx(0.28 * 600_000 - 60_000)  # fator R = 28%
    assert v.tributos_empresa == pytest.approx(600_000 * 0.195 - 9_900)
    assert lp.tributos_empresa == pytest.approx(impostos.lucro_presumido(600_000, 0.02).total)
    assert lp.lucros == pytest.approx(600_000 - 90_000 - 60_000 - lp.tributos_empresa - 1518 * 12 - 1518 * 12 * 0.2 - 6_000)
    assert pf.pro_labore == 450_000 and pf.liquido_dono < min(iii.liquido_dono, lp.liquido_dono)
    assert e.melhor in c and e.economia_vs_atual == pytest.approx(c[e.melhor].liquido_dono - pf.liquido_dono)
    grande = empresario.comparar(Empresa(faturamento_anual=6_000_000, despesas_anuais=1_000_000))
    assert not next(x for x in grande.cenarios if x.nome.startswith("Simples")).aplicavel


# ---------------------------------------------------------------- plano completo e relatório
def test_planejamento_completo_gera_relatorio(tmp_path):
    from quiron.servicos.analise.fila import carregar_tipos
    from quiron.servicos.analise.tipos.planejamento import completo, empresario as tipo_empresario

    tipos = carregar_tipos()
    assert {"planejamento_completo", "aposentadoria", "sucessao", "tributario", "protecao", "empresario"} <= set(tipos)
    ficha.salvar(cliente())
    rel = completo({"cliente": "CLI-101"}, redigir=False)
    titulos = [s.titulo for s in rel.secoes]
    assert titulos[0] == "Plano de ação" and "Aposentadoria" in titulos and "Sucessão" in titulos
    assert "Empresário: pessoa física × pessoa jurídica" not in titulos  # sem empresa na ficha
    acoes = [a["acao"] for a in rel.fatos["acoes"]]
    assert acoes[0].startswith(("Quitar", "Contratar", "Plano de saúde")) and any("Cheque especial" in a for a in acoes)
    assert rel.fatos["sucessao"]["itcmd"] == pytest.approx(47_600)
    assert "Rascunho de planejamento" in rel.rodape
    caminhos = rel.salvar(tmp_path / "rel")
    assert caminhos["pdf"].stat().st_size > 30_000 and caminhos["planilha"].exists()
    with pytest.raises(ValueError, match="empresa"):
        tipo_empresario({"cliente": "CLI-101"}, redigir=False)
    with pytest.raises(FichaInvalida):
        completo({"cliente": "CLI-999"}, redigir=False)


# ---------------------------------------------------------------- LGPD
def test_esquecer_cliente_apaga_tudo_e_so_dele(dados):
    from quiron.servicos import lgpd
    from quiron.servicos.analise.fila import Fila
    from quiron.runtime.memoria import Memoria

    ficha.salvar(cliente(cliente="CLI-01"))
    ficha.salvar(cliente(cliente="CLI-012"))
    ficha.salvar({"cliente": "CLI-012", "idade": 46})  # gera histórico
    (dados / "carteiras").mkdir()
    (dados / "carteiras" / "CART-1.json").write_text(json.dumps({"cliente": "CLI-012", "posicoes": []}))
    (dados / "carteiras" / "CART-2.json").write_text(json.dumps({"cliente": "CLI-01", "posicoes": []}))
    fila = Fila()
    t = fila.pedir("planejamento_completo", {"cliente": "CLI-012"})
    fila.pedir("planejamento_completo", {"cliente": "CLI-01"})
    m = Memoria()
    m.guardar(1, "user", "monte o plano do CLI-012")
    m.guardar(1, "user", "e o do CLI-01?")
    ws = dados / "workspace"
    ws.mkdir()
    (ws / "MEMORIA.md").write_text("- CLI-012 prefere renda fixa\n- CLI-01 é aposentado\n", encoding="utf-8")
    r = lgpd.esquecer_cliente("CLI-012")
    assert r.itens["fichas/versões"] == 2 and r.itens["carteiras"] == 1 and r.itens["relatórios"] == 1
    assert r.itens["mensagens de conversa"] == 1 and r.itens["linhas de memória/diário"] == 1
    assert ficha.existe("CLI-01") and not ficha.existe("CLI-012")
    assert (dados / "carteiras" / "CART-2.json").exists() and fila.obter(t.id) is None
    assert "CLI-01 é aposentado" in (ws / "MEMORIA.md").read_text(encoding="utf-8")
    con = sqlite3.connect(dados / "conversas.db")
    assert [x[0] for x in con.execute("SELECT texto FROM mensagens")] == ["e o do CLI-01?"]
    assert "Nada guardado" in lgpd.esquecer_cliente("CLI-012").descrever()


# ---------------------------------------------------------------- MCP
def test_servidor_assessoria_responde(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cfg = json.loads((RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["quiron-assessoria"]
    env = {**os.environ, "QUIRON_DADOS": str(tmp_path)}
    params = StdioServerParameters(command=shutil.which(cfg["command"]), args=cfg["args"], cwd=str(RAIZ), env=env)

    async def rodar():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                nomes = {t.name for t in (await s.list_tools()).tools}
                salvo = await s.call_tool("salvar_ficha", {"cliente": "CLI-777", "dados": {"idade": 52, "uf": "MG"}})
                recusa = await s.call_tool("salvar_ficha", {"cliente": "Maria", "dados": {"idade": 30}})
                lista = await s.call_tool("fichas_de_clientes", {})
                apagado = await s.call_tool("esquecer_cliente", {"cliente": "CLI-777"})
                return nomes, salvo, recusa, lista, apagado

    nomes, salvo, recusa, lista, apagado = asyncio.run(rodar())
    assert {"campos_da_ficha", "salvar_ficha", "ver_ficha", "fichas_de_clientes", "esquecer_cliente"} <= nomes
    assert "Ficha CLI-777" in salvo.content[0].text and "Falta:" in salvo.content[0].text
    assert "CLI-XXX" in recusa.content[0].text and "CLI-777: 52 anos" in lista.content[0].text
    assert "CLI-777 esquecido" in apagado.content[0].text
