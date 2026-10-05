"""Servidor MCP `quiron-mercado`: dados de mercado de fontes públicas e oficiais, sempre com fonte e horário."""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from quiron.servicos.mercado import abertos, painel

mcp = MCPServer(
    "quiron-mercado",
    instructions=(
        "Dados de mercado (Banco Central, Tesouro, ANBIMA, IBGE, CVM, brapi, Yahoo, Damodaran). "
        "Use SOMENTE os números devolvidos, sempre com a fonte e o horário (📊 Fonte — horário). "
        "Se um dado vier indisponível ou desatualizado, diga isso; nunca estime nem complete de memória. "
        "Para o briefing, siga agente/skills/briefing.md."
    ),
)


@mcp.tool()
def cotacao(ativos: list[str]) -> str:
    """Cotação com variação do dia. Ex.: ["PETR4", "IBOV", "USDBRL", "^GSPC", "ouro"]. B3 tem atraso de ~15 min."""
    return "\n".join(painel.cotacao(a) for a in ativos)


@mcp.tool()
def watchlist() -> str:
    """Cotações de todos os ativos de config/watchlist.yaml."""
    return painel.watchlist()


@mcp.tool()
def taxas() -> str:
    """Selic meta, CDI e taxas atuais do Tesouro Direto (Selic, Prefixado, IPCA+)."""
    return painel.taxas()


@mcp.tool()
def curva_juros() -> str:
    """Curva de juros pré, real (IPCA+) e inflação implícita por prazo (ETTJ ANBIMA; plano B: Tesouro)."""
    return painel.texto_curva()


@mcp.tool()
def macro() -> str:
    """IPCA, IGP-M, câmbio PTAX, IBC-Br, desemprego e medianas do Focus (com a mudança da semana)."""
    return painel.macro()


@mcp.tool()
def focus(ano: int | None = None) -> str:
    """Medianas do Focus (IPCA, PIB, Selic, câmbio) para um ano (padrão: ano corrente)."""
    return painel.texto_focus(ano)


@mcp.tool()
def agenda(dias: int = 7) -> str:
    """Agenda econômica: divulgações do IBGE + Copom e resultados de empresas (config/agenda_fixa.yaml)."""
    return painel.agenda(dias)


@mcp.tool()
def briefing() -> str:
    """Dados do briefing do dia (juros, inflação, Focus, câmbio, bolsa, agenda). Redija seguindo a skill briefing."""
    return painel.briefing()


@mcp.tool()
def companhia(termo: str) -> str:
    """Busca companhia aberta na CVM por nome ou CNPJ (cadastro: CNPJ, código CVM, setor)."""
    achados, fonte = abertos.buscar_companhia(termo)
    if not achados:
        return f"Nenhuma companhia ativa encontrada para '{termo}'. {fonte}"
    linhas = [f"- **{a['nome']}** — CNPJ {a['cnpj']} · código CVM {a['codigo_cvm']} · {a['setor']}" for a in achados]
    return "\n".join(linhas + [fonte])


@mcp.tool()
def fundo_cotas(cnpj: str, mes: str | None = None) -> str:
    """Cotas diárias de um fundo (informe diário da CVM). mes opcional no formato AAAA-MM."""
    m = date.fromisoformat(mes + "-01") if mes else None
    cotas, fonte = abertos.informe_diario(cnpj, m)
    if not cotas:
        return f"Nenhuma cota encontrada para o CNPJ {cnpj}. {fonte}"
    ini, fim = cotas[0], cotas[-1]
    rent = (fim.cota / ini.cota - 1) * 100
    linhas = [
        f"Fundo {cnpj}: {len(cotas)} dias, de {ini.data:%d/%m/%Y} a {fim.data:%d/%m/%Y}",
        f"- Cota: {ini.cota:.6f} → {fim.cota:.6f} ({rent:+.2f}% no período)".replace(".", ","),
    ]
    if fim.patrimonio:
        linhas.append(f"- Patrimônio líquido: R$ {fim.patrimonio:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    if fim.cotistas:
        linhas.append(f"- Cotistas: {fim.cotistas}")
    return "\n".join(linhas + [fonte])


@mcp.tool()
def buscar_fundo(termo: str, limite: int = 8) -> str:
    """Procura fundos no cadastro da CVM por nome (ex.: "kapitalo kappa") ou CNPJ. Devolve CNPJ, classificação ANBIMA,
    gestora e PL — use o CNPJ nas análises de fundos (quiron_analise: fundo_analise, fundos_comparativo...)."""
    from quiron.servicos.fundos import cvm

    try:
        achados = cvm.buscar(termo, max(1, min(limite, 20)))
    except Exception as e:  # noqa: BLE001
        return f"Cadastro da CVM indisponível agora ({type(e).__name__})."
    if not achados:
        return f"Nenhum fundo em funcionamento com “{termo}” no nome. Tente menos palavras ou o CNPJ."
    br = lambda v: f"R$ {v:,.0f}".replace(",", ".") if v else "—"  # noqa: E731
    def marca(c) -> str:
        n = c.nome.upper()
        if "MASTER" in n:
            return " ⚠️ master (veículo interno; o cliente acessa por um fundo de cotas)"
        if "ESPELHO" in n:
            return " (espelho de distribuidor)"
        if "PREVID" in n or "PREV " in n:
            return " (previdência)"
        return ""

    achados.sort(key=lambda c: "MASTER" in c.nome.upper())  # masters por último
    linhas = [f"- **{c.nome}** — CNPJ {c.cnpj_formatado} · {c.anbima or c.classificacao or c.tipo} · gestora "
              f"{c.gestor or '?'} · PL {br(c.pl)}{marca(c)}" for c in achados]
    return "\n".join(linhas + [cvm.fonte()])


@mcp.tool()
def buscar_gestora(termo: str) -> str:
    """Gestoras no cadastro da CVM que batem com o termo, com o número de classes e o PL (para a análise 'gestora')."""
    from quiron.servicos.fundos import cvm

    classes, nomes = cvm.fundos_da_gestora(termo)
    if not nomes:
        return f"Nenhuma gestora com “{termo}”."
    por = {}
    for c in classes:
        n, pl = por.get(c.gestor, (0, 0.0))
        por[c.gestor] = (n + 1, pl + (c.pl or 0))
    linhas = [f"- {g}: {n} classes em funcionamento, PL somado R$ {pl:,.0f} (inclui fundos de cotas)".replace(",", ".")
              for g, (n, pl) in sorted(por.items(), key=lambda x: -x[1][1])]
    return "\n".join(linhas + [cvm.fonte()])


@mcp.tool()
def fii_dados(ticker: str) -> str:
    """Último informe mensal de um FII na CVM (VP da cota, PL, cotistas, DY e rentabilidade do mês, segmento)."""
    from quiron.servicos.fundos import cvm

    try:
        h = cvm.fii(ticker)
    except cvm.FundoNaoEncontrado as e:
        return str(e)
    u = h[-1]
    dy12 = sum(x["dy_mes"] or 0 for x in h[-12:])
    return (f"{u['ticker'] or ticker} — {u['nome']} · {u['segmento']} · informe {u['mes']}\n"
            f"- VP/cota R$ {u['vp_cota'] or 0:.2f} · PL R$ {u['pl'] or 0:,.0f} · cotistas {u['cotistas']}\n"
            f"- DY do mês {u['dy_mes'] or 0:.2f}% (12m: {dy12:.2f}% sobre o VP) · rentabilidade efetiva {u['rent_efetiva'] or 0:.2f}%\n"
            .replace(",", "X").replace(".", ",").replace("X", ".") + cvm.fonte())


@mcp.tool()
def damodaran(dataset: str, termo: str) -> str:
    """Procura um termo nos datasets do Damodaran. dataset: premio_pais, erp_historico, betas_eua,
    betas_emergentes, multiplos_eua, ev_ebitda_emergentes. Ex.: damodaran("premio_pais", "Brazil")."""
    if dataset not in abertos.DATASETS_DAMODARAN:
        return "Datasets: " + ", ".join(f"{k} ({v[1]})" for k, v in abertos.DATASETS_DAMODARAN.items())
    return abertos.buscar_damodaran(dataset, termo)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
