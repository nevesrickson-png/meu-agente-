"""Depuração geral (05/10/2026): regras que faltavam ou casos de borda encontrados na revisão."""

from quiron.servicos import calculadoras


def test_iof_regressivo_oficial_e_aplicado_no_cdb():
    tabela = {1: 0.96, 2: 0.93, 4: 0.86, 10: 0.66, 15: 0.50, 29: 0.03, 30: 0.0, 400: 0.0}
    assert {d: calculadoras.aliquota_iof(d) for d in tabela} == tabela
    curto = calculadoras.cdb_x_isento(11, 13.5, 10)  # 10 dias: IOF leva 66% do rendimento
    linhas = dict(curto.linhas)
    assert linhas["CDB líquido"].startswith("3,5") and linhas["Melhor no prazo"].startswith("Isento")
    assert any("IOF de 66%" in m for m in curto.memoria)
    longo = calculadoras.cdb_x_isento(11, 13.5, 720)
    assert not any("IOF" in m for m in longo.memoria)


def test_datas_proxima_meio_dia_e_relativo(tmp_path, monkeypatch):
    from datetime import date, datetime

    from quiron.runtime.agendador import BRT
    from quiron.servicos.assessoria import datas

    sexta = date(2026, 10, 2)
    assert datas.extrair("próxima sexta ligar CLI-012", sexta) == ("Ligar CLI-012", date(2026, 10, 9), None)
    assert datas.extrair("ao meio-dia almoço com CLI-003", sexta) == ("Almoço com CLI-003", None, (12, 0))
    assert datas.extrair("meio dia e meia reunião", sexta)[2] == (12, 30)
    agora = datetime(2026, 10, 2, 9, 40, tzinfo=BRT)
    assert datas.relativo("daqui a 2 horas ligar", agora) == ("ligar", datetime(2026, 10, 2, 11, 40, tzinfo=BRT))
    assert datas.relativo("em 30 minutos", agora)[1] == datetime(2026, 10, 2, 10, 10, tzinfo=BRT)
    assert datas.relativo("em 3 dias", agora) == ("em 3 dias", None)  # dias ficam com interpretar()

    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    from quiron.servicos.organizacao import tarefas

    t = tarefas.criar("daqui a 2 horas ligar para o CLI-012", agora)
    assert (t.texto, t.prazo, t.hora) == ("Ligar para o CLI-012", "2026-10-02", "11:40")
    assert tarefas.adiar(t.id, "daqui a meia hora", agora).hora == "10:10"
