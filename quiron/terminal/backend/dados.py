"""Dados do Terminal em JSON, montados a partir dos MESMOS serviços usados pelos MCP (sem duplicar busca).

Cada função devolve um dict pronto para a tela. Falha de uma fonte vira {"erro": "..."} no item, nunca derruba o painel.
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable
from zoneinfo import ZoneInfo

from quiron.nucleo import regras
from quiron.servicos.mercado import bcb, cotacoes, curva, http, painel, tesouro
from quiron.servicos.mercado.http import FonteIndisponivel
from quiron.servicos.noticias import coleta, redes, sentimento
from quiron.servicos.noticias import consultas as noticias_consultas

BRT = ZoneInfo("America/Sao_Paulo")
INICIO = time.time()

GRUPOS = {
    "wei": [("^BVSP", "Ibovespa"), ("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones"), ("^FTSE", "FTSE 100"),
            ("^GDAXI", "DAX"), ("^N225", "Nikkei"), ("^HSI", "Hang Seng"), ("000001.SS", "Xangai")],
    "fx": [("BRL=X", "Dólar (USD/BRL)"), ("EURBRL=X", "Euro (EUR/BRL)"), ("GBPBRL=X", "Libra (GBP/BRL)"), ("EURUSD=X", "EUR/USD"),
           ("JPY=X", "USD/JPY"), ("CNY=X", "USD/CNY"), ("DX-Y.NYB", "DXY (dólar global)")],
    "cmdty": [("BZ=F", "Petróleo Brent"), ("CL=F", "Petróleo WTI"), ("GC=F", "Ouro"), ("SI=F", "Prata"), ("TIO=F", "Minério de ferro"),
              ("ZS=F", "Soja"), ("ZC=F", "Milho"), ("KC=F", "Café"), ("HG=F", "Cobre")],
}


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quiron-fundo")
_fundo: dict[str, tuple[Future, float]] = {}


def _em_segundo_plano(nome: str, func: Callable[[], Any], validade: int = 600) -> Any:
    """Para fontes lentas (ex.: arquivo do Tesouro, 13 MB): devolve o último resultado pronto, ou None se ainda
    estiver baixando pela primeira vez. Quando o resultado passa da validade, busca de novo em segundo plano."""
    tarefa, quando = _fundo.get(nome, (None, 0.0))
    if tarefa is None or (tarefa.done() and time.time() - quando > validade):
        nova = _executor.submit(func)
        _fundo[nome] = (nova, time.time())
        if tarefa is None or tarefa.exception() is not None:
            tarefa = nova
    if not tarefa.done():
        return None
    if tarefa.exception() is not None:
        _fundo.pop(nome, None)  # mostra o erro uma vez e tenta de novo no próximo pedido
    return tarefa.result()


def _iso(d: datetime | None, brasilia: bool = False) -> str | None:
    """Data/hora em ISO UTC. Sem fuso: hora do relógio do sistema (horários de consulta) ou, com
    `brasilia=True`, hora de Brasília (eventos de agenda, como "Copom 18:30")."""
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=BRT) if brasilia else d.astimezone()
    return d.astimezone(timezone.utc).isoformat()


def _seguro(func: Callable[[], Any]) -> Any:
    try:
        return func()
    except (FonteIndisponivel, ValueError, KeyError) as e:
        return {"erro": str(e)[:200]}


# ---------------------------------------------------------------- cotações


def _cot(c: cotacoes.Cotacao, nome: str | None = None) -> dict:
    return {"ativo": c.ativo, "nome": nome or c.nome, "preco": c.preco, "variacao": c.variacao_pct, "moeda": c.moeda,
            "horario": _iso(c.horario), "fonte": c.fonte, "obtido_em": _iso(c.obtido_em), "atraso": c.atraso}


def _normalizar(ativo: str) -> str:
    a = ativo.strip()
    return a.upper() if re.fullmatch(r"[A-Za-z]{4}\d{1,2}", a) or a.upper() in {"IBOV", "IFIX", "SMLL", "USDBRL", "EURBRL"} else a


def cotacao(ativo: str) -> dict:
    return _seguro(lambda: _cot(cotacoes.cotacao(_normalizar(ativo))))


def watchlist() -> list[dict]:
    from quiron.nucleo.config import ler_yaml

    w = ler_yaml("watchlist") or {}
    ativos = [*w.get("indices", []), *w.get("moedas", []), *w.get("acoes", []), *w.get("fiis", []), *w.get("etfs", []), *w.get("commodities", [])]
    saida = []
    for a in ativos:
        item = cotacao(str(a))
        saida.append(item if "erro" not in item else {"ativo": str(a), **item})
    return saida


def grupo(nome: str) -> list[dict]:
    saida = []
    for simbolo, rotulo in GRUPOS[nome]:
        try:
            saida.append(_cot(cotacoes.yahoo(simbolo), rotulo))
        except FonteIndisponivel as e:
            saida.append({"ativo": simbolo, "nome": rotulo, "erro": str(e)[:150]})
    return saida


def historico(ativo: str, periodo: str = "6mo", comparar: str | None = None) -> dict:
    """Fechamentos + médias móveis de 20 e 50 dias; com `comparar`, as duas séries em base 100."""
    pontos = cotacoes.historico(ativo, periodo)
    datas = [d.date().isoformat() for d, _ in pontos]
    valores = [v for _, v in pontos]

    def media(n: int) -> list[float | None]:
        return [None if i + 1 < n else sum(valores[i + 1 - n : i + 1]) / n for i in range(len(valores))]

    dados: dict[str, Any] = {"ativo": ativo, "periodo": periodo, "datas": datas, "fonte": "Yahoo Finance",
                             "obtido_em": _iso(datetime.now())}
    if comparar:
        outro = dict((d.date().isoformat(), v) for d, v in cotacoes.historico(comparar, periodo))
        comuns = [d for d in datas if d in outro]
        base_a = valores[datas.index(comuns[0])] if comuns else 1
        base_b = outro[comuns[0]] if comuns else 1
        dados.update(datas=comuns, modo="comparacao", comparar=comparar,
                     series={ativo: [valores[datas.index(d)] / base_a * 100 for d in comuns],
                             comparar: [outro[d] / base_b * 100 for d in comuns]})
    else:
        dados.update(modo="medias", series={ativo: valores, "Média 20d": media(20), "Média 50d": media(50)})
    return dados


def ativo(ticker: str) -> dict:
    """Visão do ativo: cotação, gráfico de 3 meses e notícias relacionadas."""
    t = _normalizar(ticker)
    hist = _seguro(lambda: historico(t, "3mo"))
    noticias_rel = _seguro(lambda: noticias(t, 72, 8))
    return {"cotacao": cotacao(t), "historico": hist, "noticias": noticias_rel}


# ---------------------------------------------------------------- juros, curva, macro


def _serie(chave: str) -> dict:
    s = bcb.sgs(chave, 2)
    return {"chave": chave, "nome": s.nome, "unidade": s.unidade, "valor": s.ultimo.valor, "data": s.ultimo.data.isoformat(),
            "anterior": s.pontos[-2].valor if len(s.pontos) > 1 else None, "fonte": s.fonte, "obtido_em": _iso(s.obtido_em),
            "desatualizado": s.desatualizado}


def juros() -> dict:
    def _tesouro() -> dict:
        tab = tesouro.titulos_atuais()
        itens = []
        for chave in ("selic", "prefixado", "ipca_mais"):
            for t in tesouro.por_tipo(tab, chave):
                itens.append({"tipo": chave, "nome": t.nome, "taxa": t.taxa_compra or t.taxa_venda, "vencimento": t.vencimento.isoformat()})
        return {"data_base": tab.data_base.isoformat(), "titulos": itens, "fonte": tab.fonte, "obtido_em": _iso(tab.obtido_em)}

    series = [_seguro(lambda c=c: _serie(c)) for c in ("selic_meta", "cdi", "selic_efetiva")]
    tes = _seguro(lambda: _em_segundo_plano("tesouro", _tesouro))
    if tes is None:  # primeira vez: o painel mostra Selic/CDI já e o Tesouro chega em seguida
        return {"series": series, "tesouro": {"carregando": True}, "parcial": True}
    return {"series": series, "tesouro": tes}


def curva_juros() -> dict:
    c = curva.curva()
    return {"data": c.data.isoformat(), "fonte": c.fonte, "obtido_em": _iso(c.obtido_em), "observacao": c.observacao,
            "desatualizado": c.desatualizado,
            "vertices": [{"anos": round(v.anos, 3), "du": v.dias_uteis, "pre": v.pre, "real": v.real, "implicita": v.implicita}
                         for v in c.vertices if v.anos <= 15]}


def macro() -> dict:
    def _focus() -> dict:
        itens, fonte = [], None
        for ind in ("ipca", "pib", "selic", "cambio"):
            try:
                e = bcb.focus(ind)
                itens.append({"indicador": e.indicador, "ano": e.ano, "mediana": e.mediana, "anterior": e.mediana_semana_anterior,
                              "data": e.data.isoformat()})
                fonte = {"fonte": e.fonte, "obtido_em": _iso(e.obtido_em)}
            except (FonteIndisponivel, ValueError) as err:
                itens.append({"indicador": bcb.INDICADORES_FOCUS[ind], "erro": str(err)[:120]})
        return {"itens": itens, **(fonte or {})}

    chaves = ("ipca_12m", "ipca_mes", "igpm_mes", "dolar_ptax", "euro_ptax", "ibc_br", "desemprego")
    return {"series": [_seguro(lambda c=c: _serie(c)) for c in chaves], "focus": _seguro(_focus)}


# ---------------------------------------------------------------- notícias, redes, agenda


def _noticia(n: coleta.Noticia) -> dict:
    t = sentimento.tom(n.titulo)
    return {"titulo": n.titulo, "link": n.link, "fonte": n.fonte, "grupo": n.grupo, "publicado_em": _iso(n.publicado_em),
            "temas": n.temas, "ativos": n.ativos, "alertas": n.alertas, "outras_fontes": n.outras_fontes, "tom": t.rotulo}


def noticias(termo: str | None = None, horas: int = 24, limite: int = 30) -> dict:
    noticias_consultas._garantir_coleta()
    lista = noticias_consultas._filtrar(coleta.listar(horas), termo)
    if not lista and termo:
        lista = noticias_consultas._filtrar(coleta.listar(720), termo)
    tom = sentimento.tom_medio([n.titulo for n in lista])
    return {"termo": termo, "total": len(lista), "tom": {"rotulo": tom.rotulo, "nota": tom.nota},
            "itens": [_noticia(n) for n in lista[:limite]]}


def top(horas: int = 12, limite: int = 25) -> dict:
    from quiron.servicos.noticias import relevancia

    hist = relevancia.diversificar(noticias_consultas.historias(horas), limite, max_por_tema=4)
    itens = []
    for h in hist:  # uma linha por história; "outras_fontes" = quem mais cobriu
        principal = next(n for n in h.itens if n.fonte == h.fonte)
        item = _noticia(principal)
        item["outras_fontes"] = h.fontes[1:]
        item["relevancia"] = round(h.nota, 1)
        itens.append(item)
    return {"termo": None, "total": len(itens), "itens": itens}


def redes_sociais(termo: str) -> dict:
    saida = {}
    for nome, func in redes.REDES.items():
        try:
            posts = func(termo)
            t = sentimento.tom_medio([p.texto for p in posts])
            saida[nome] = {"tom": {"rotulo": t.rotulo, "nota": t.nota}, "posts": [
                {"autor": p.autor, "texto": p.texto[:280], "link": p.link, "publicado_em": _iso(p.publicado_em),
                 "engajamento": p.engajamento, "detalhe": p.detalhe} for p in sorted(posts, key=lambda p: -p.engajamento)[:10]]}
        except redes.RedeNaoConfigurada as e:
            saida[nome] = {"configurar": str(e)}
        except FonteIndisponivel as e:
            saida[nome] = {"erro": str(e)[:150]}
    return {"termo": termo, "redes": saida}


def agenda(dias: int = 7) -> dict:
    inicio = datetime.combine(date.today(), datetime.min.time())
    fim = inicio + timedelta(days=dias + 1)
    eventos = [{"quando": _iso(e.quando, brasilia=True), "titulo": e.titulo, "fonte": e.fonte}
               for e in painel.eventos_fixos() if inicio <= e.quando < fim]
    erro = None
    try:
        from quiron.servicos.mercado import abertos

        eventos += [{"quando": _iso(d.quando, brasilia=True), "titulo": d.titulo, "fonte": d.fonte} for d in abertos.calendario_ibge(dias)]
    except (FonteIndisponivel, ValueError) as e:
        erro = str(e)[:150]
    eventos.sort(key=lambda e: e["quando"])
    return {"dias": dias, "eventos": eventos, "erro": erro}


# ---------------------------------------------------------------- status


def status() -> dict:
    import psutil

    proc = psutil.Process(os.getpid())
    with http._banco() as con:
        fontes = con.execute("SELECT fonte, MAX(obtido_em) FROM cache GROUP BY fonte ORDER BY 2 DESC LIMIT 20").fetchall()
    try:
        from quiron.servicos.analise.fila import fila

        tarefas = fila().listar(50)
        analises = {"na_fila": sum(t.situacao == "na fila" for t in tarefas),
                    "rodando": sum(t.situacao == "rodando" for t in tarefas),
                    "ultima": tarefas[0].descrever() if tarefas else ""}
    except Exception:  # noqa: BLE001
        analises = {}
    return {
        "analises": analises,
        "memoria_mb": round(proc.memory_info().rss / 1e6, 1),
        "memoria_sistema_pct": psutil.virtual_memory().percent,
        "no_ar_desde": _iso(datetime.fromtimestamp(INICIO)),
        "fontes": [{"fonte": f, "atualizado_em": _iso(datetime.fromtimestamp(t))} for f, t in fontes],
        "regras_pendentes": regras.avisos(),
        "redes": {n: bool(redes._env(v)) for n, v in
                  {"bluesky": "BLUESKY_APP_PASSWORD", "reddit": "REDDIT_CLIENT_ID", "youtube": "YOUTUBE_API_KEY"}.items()},
    }



# ---------------------------------------------------------------- Terminal v2 (Fase 12): telas de análise
def fa(ticker: str) -> dict:
    """FA: demonstrações e indicadores da CVM (DFP/ITR) + múltiplos com a cotação do dia."""
    def montar() -> dict:
        from quiron.servicos.analise.tipos.valuation import coletar
        from quiron.servicos.valuation import dcf

        col = coletar(ticker, anos=5)
        mu = dcf.multiplos(col.base, col.preco, col.acoes, col.dividendos_12m)
        campos = ("receita", "ebitda", "ebit", "lucro_controladores", "fco", "capex", "divida_liquida", "pl")
        periodos = [{"rotulo": p.rotulo, **{k: p[k] for k in campos}} for p in col.anuais + [col.base]]
        return {"empresa": col.empresa.nome, "ticker": col.ticker, "tickers": col.empresa.tickers, "setor": col.empresa.setor,
                "segmento": col.empresa.segmento, "descricao": col.empresa.descricao[:400], "preco": col.preco,
                "periodos": periodos, "multiplos": {k: getattr(mu, k) for k in mu.__dataclass_fields__},
                "acoes": col.acoes, "avisos": col.avisos, "fontes": col.fontes}

    r = _em_segundo_plano(f"fa:{ticker.upper()}", montar, validade=3600)
    if r is None:
        return {"parcial": True, "carregando": True, "ticker": ticker.upper()}
    return r


def fundos_busca(termo: str) -> dict:
    """FUND: fundos no cadastro da CVM + rentabilidade de 12 meses pelo índice mensal (se já baixado)."""
    from quiron.servicos.fundos import cvm

    itens = []
    for c in cvm.buscar(termo, 12):
        ret12 = None
        try:
            linhas, _ = cvm.serie_mensal(c.cnpj)
            fechadas = [x for x in linhas if x["mes"] < date.today().strftime("%Y-%m")]
            if len(fechadas) >= 13:
                ret12 = (fechadas[-1]["cota"] / fechadas[-13]["cota"] - 1) * 100
        except Exception:  # noqa: BLE001 — índice ainda não baixado
            pass
        itens.append({"cnpj": c.cnpj_formatado, "nome": c.nome, "anbima": c.anbima or c.classificacao, "gestor": c.gestor,
                      "pl": c.pl, "ret12": ret12, "master": "MASTER" in c.nome.upper()})
    return {"termo": termo, "itens": itens, "fonte": "CVM Dados Abertos", "obtido_em": _iso(datetime.now())}


def plano(cliente: str = "") -> dict:
    """PLAN: ficha de planejamento do cliente (CLI-XXX) ou a lista de fichas."""
    from quiron.servicos.planejamento import ficha as fichas

    if not cliente:
        return {"lista": [{"cliente": f.cliente, "idade": f.idade, "ocupacao": f.ocupacao, "patrimonio": f.patrimonio_total,
                           "atualizado_em": f.atualizado_em[:10]} for f in fichas.listar()]}
    f = fichas.carregar(cliente)
    return {"cliente": f.cliente, "resumo": fichas.descrever(f), "pendencias": f.validar(), "patrimonio": f.patrimonio_total,
            "financeiro": f.investimentos, "renda": f.renda_mensal_bruta, "despesas": f.despesas_mensais,
            "objetivos": [{"nome": o.nome, "valor": o.valor, "prazo": o.prazo_anos} for o in f.objetivos]}


def academia() -> dict:
    """ACAD: painel geral da Academia + diagnóstico por módulo da área ativa."""
    from quiron.servicos.academia import diagnostico, estudo
    from quiron.servicos.academia.banco import Banco

    banco = Banco()
    ativa = estudo.area_ativa(banco)
    mods = diagnostico.diagnosticar(banco, ativa)
    return {"area": ativa, "nome": diagnostico.nome_area(ativa), "prontidao": diagnostico.prontidao(mods),
            "modulos": [{"numero": m.numero, "titulo": m.titulo, "peso": m.peso, "respostas": m.respostas,
                         "acerto": m.acerto_bruto} for m in mods],
            "texto": diagnostico.painel_geral(banco, ativa)}


def tarefas() -> dict:
    """TASK: lembretes e tarefas agendadas (os mesmos do Telegram)."""
    from quiron.runtime.agendador import Agendador

    from quiron.servicos.organizacao import tarefas as org

    hoje = datetime.now().date()
    return {"itens": [{"id": a.id, "texto": a.texto, "tipo": a.tipo, "recorrencia": a.recorrencia,
                       "proxima": _iso(a.proxima, brasilia=True)} for a in Agendador().listar() if not a.texto.startswith("[T")],
            "tarefas": [{"id": t.id, "texto": t.texto, "prazo": t.prazo, "hora": t.hora, "atrasada": t.atrasada(hoje),
                         "descricao": t.descrever(hoje)} for t in org.listar("pendentes", hoje)]}


def alertas_lista() -> dict:
    """ALRT: alertas ativos (avaliados pelo bot a cada 5 minutos ou pelo botão "avaliar agora")."""
    from quiron.servicos import alertas

    return {"itens": [{**a.__dict__, "descricao": a.descrever()} for a in alertas.listar()], "tipos": alertas.TIPOS}


# Tópicos que a tela pode assinar pelo WebSocket: função + intervalo de atualização (segundos)
TOPICOS: dict[str, tuple[Callable[..., Any], int]] = {
    "watchlist": (watchlist, 60),
    "cotacao": (cotacao, 60),
    "grupo": (grupo, 60),
    "ativo": (ativo, 60),
    "historico": (historico, 300),
    "juros": (juros, 1800),
    "curva": (curva_juros, 3600),
    "macro": (macro, 1800),
    "noticias": (noticias, 300),
    "top": (top, 300),
    "redes": (redes_sociais, 900),
    "agenda": (agenda, 3600),
    "status": (status, 15),
    "fa": (fa, 3600),
    "fundos": (fundos_busca, 3600),
    "plano": (plano, 120),
    "academia": (academia, 300),
    "tarefas": (tarefas, 60),
    "alertas": (alertas_lista, 60),
}
