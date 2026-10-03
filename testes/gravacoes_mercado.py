"""Respostas gravadas no formato das fontes oficiais (valores ilustrativos, não são dados reais)."""

import io
import json
import zipfile

import httpx

SGS = {
    432: [{"data": "18/09/2026", "valor": "15.00"}, {"data": "02/10/2026", "valor": "15.00"}],
    4389: [{"data": "01/10/2026", "valor": "14.90"}, {"data": "02/10/2026", "valor": "14.90"}],
    13522: [{"data": "01/07/2026", "valor": "4.95"}, {"data": "01/08/2026", "valor": "4.80"}],
    433: [{"data": "01/07/2026", "valor": "0.26"}, {"data": "01/08/2026", "valor": "-0.11"}],
    189: [{"data": "01/08/2026", "valor": "0.20"}, {"data": "01/09/2026", "valor": "0.35"}],
    1: [{"data": "01/10/2026", "valor": "5.3412"}, {"data": "02/10/2026", "valor": "5.3120"}],
    21619: [{"data": "01/10/2026", "valor": "6.2100"}, {"data": "02/10/2026", "valor": "6.2000"}],
    24364: [{"data": "01/06/2026", "valor": "108.10"}, {"data": "01/07/2026", "valor": "108.50"}],
    24369: [{"data": "01/06/2026", "valor": "5.80"}, {"data": "01/07/2026", "valor": "5.60"}],
}

FOCUS = {
    "IPCA": [("2026-09-26", 4.85), ("2026-09-19", 4.90), ("2026-09-12", 4.95)],
    "PIB Total": [("2026-09-26", 2.10), ("2026-09-19", 2.10)],
    "Selic": [("2026-09-26", 15.00), ("2026-09-19", 15.00)],
    "Câmbio": [("2026-09-26", 5.45), ("2026-09-19", 5.50)],
}

TESOURO_CSV = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha\n"
    "Tesouro Prefixado;01/01/2029;01/10/2026;13,50;13,62;780,10;778,20;778,20\n"
    "Tesouro Prefixado;01/01/2032;01/10/2026;13,80;13,92;520,30;518,90;518,90\n"
    "Tesouro IPCA+;15/08/2029;01/10/2026;7,40;7,52;3300,10;3290,00;3290,00\n"
    "Tesouro IPCA+;15/05/2035;01/10/2026;7,10;7,22;2100,00;2090,00;2090,00\n"
    "Tesouro Selic;01/03/2029;01/10/2026;0,0450;0,0570;17500,10;17480,00;17480,00\n"
    "Tesouro Prefixado;01/01/2029;30/09/2026;13,40;13,52;781,00;779,00;779,00\n"
    "Tesouro Prefixado;01/01/2026;30/09/2025;14,00;14,10;990,00;989,00;989,00\n"
)

ETTJ_CSV = (
    "Parâmetros;Beta 1;Beta 2;Beta 3;Beta 4;Lambda 1;Lambda 2\n"
    "PREFIXADOS;0,1350;-0,0050;0,0100;0,0200;1,20;0,40\n"
    "IPCA;0,0700;0,0010;0,0050;0,0100;1,10;0,30\n"
    "\n"
    "ETTJ Inflação Implicita (IPCA)\n"
    "Vertices;ETTJ IPCA;ETTJ PREF;Inflação Implícita\n"
    "126;7,8000;14,9000;6,5862\n"
    "252;7,5000;14,2000;6,2326\n"
    "504;7,3000;13,7000;5,9645\n"
    "756;7,2500;13,6000;5,9208\n"
    "1.260;7,1500;13,7500;6,1596\n"
    "2.520;7,0000;13,9000;6,4486\n"
    "\n"
    "PREFIXADOS (CIRCULAR 3.361);;\n"
)

BRAPI = {
    "PETR4": {"results": [{"symbol": "PETR4", "shortName": "PETROBRAS PN", "longName": "Petróleo Brasileiro S.A. - Petrobras",
                           "currency": "BRL", "regularMarketPrice": 38.45, "regularMarketChangePercent": 1.25,
                           "regularMarketTime": "2026-10-02T20:07:00.000Z"}], "requestedAt": "2026-10-02T20:30:00Z"},
}

CIAS_CSV = (
    "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;DT_CONST;DT_CANCEL;MOTIVO_CANCEL;SIT;DT_INI_SIT;CD_CVM;SETOR_ATIV\n"
    "84.429.695/0001-11;WEG S.A.;WEG;1971-01-01;1961-09-16;;;ATIVO;1971-01-01;5410;Máquinas, Equipamentos, Veículos e Peças\n"
    "33.000.167/0001-01;PETROLEO BRASILEIRO S.A. PETROBRAS;PETROBRAS;1977-07-20;1953-10-03;;;ATIVO;1977-07-20;9512;Petróleo e Gás\n"
    "11.111.111/0001-11;EMPRESA CANCELADA S.A.;;2000-01-01;;2010-01-01;Liquidação;CANCELADA;2010-01-01;99999;Outros\n"
)

INF_DIARIO_CSV = (
    "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;ID_SUBCLASSE;DT_COMPTC;VL_TOTAL;VL_QUOTA;VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
    "CLASSES - FIF;12.345.678/0001-90;;2026-09-01;1000000.00;2.500000;1000000.00;0.00;0.00;120\n"
    "CLASSES - FIF;12.345.678/0001-90;;2026-09-30;1010000.00;2.525000;1010000.00;5000.00;0.00;125\n"
    "CLASSES - FIF;98.765.432/0001-10;;2026-09-30;5000.00;1.100000;5000.00;0.00;0.00;3\n"
)

IBGE = {"count": 3, "page": 1, "totalPages": 1, "items": [  # formato real: horário em UTC
    {"id": 4309, "titulo": "Índice Nacional de Preços ao Consumidor Amplo", "data_divulgacao": "09/10/2026 12:00:00",
     "tipo": "Divulgação de Indicadores", "nome_produto": "Índice Nacional de Preços ao Consumidor Amplo",
     "ano_referencia_inicio": 2026, "mes_referencia_inicio": 9},
    {"id": 4300, "titulo": "Pesquisa Nacional por Amostra de Domicílios Contínua Mensal", "data_divulgacao": "05/10/2026 12:00:00",
     "tipo": "Divulgação de Indicadores", "nome_produto": "Divulgação mensal#pnadc1",
     "ano_referencia_inicio": 0, "mes_referencia_inicio": 0},
    {"id": 3673, "titulo": "Mapa experimental", "data_divulgacao": "06/10/2026 13:00:00",
     "tipo": "Investigações Experimentais", "nome_produto": "", "ano_referencia_inicio": 0, "mes_referencia_inicio": 0},
]}


# Formato real do web service SGS (www3.bcb.gov.br): XML escapado dentro do envelope SOAP
SGS_SOAP = {
    13522: [("5/2026", "4.72"), ("6/2026", "4.64"), ("7/2026", "4.44"), ("8/2026", "4.22")],
    432: [("1/10/2026", "13,75"), ("2/10/2026", "13,75"), ("4/11/2099", "13,75")],
}


def _soap(codigo: int) -> str:
    itens = "".join(f"<ITEM><DATA>{d}</DATA><VALOR>{v}</VALOR><BLOQUEADO>false</BLOQUEADO></ITEM>" for d, v in SGS_SOAP[codigo])
    xml = f"<?xml version='1.0' encoding='ISO-8859-1'?><SERIES><SERIE ID='{codigo}'>{itens}</SERIE></SERIES>"
    escapado = xml.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<?xml version="1.0" encoding="utf-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soapenv:Body><ns1:getValoresSeriesXMLResponse><getValoresSeriesXMLReturn>{escapado}</getValoresSeriesXMLReturn>"
        "</ns1:getValoresSeriesXMLResponse></soapenv:Body></soapenv:Envelope>"
    )


def _zip(nome: str, texto: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, texto.encode("latin-1"))
    return buf.getvalue()


def roteador(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    host = request.url.host
    if host == "olinda.bcb.gov.br" and "+" in request.url.query.decode():
        # o Olinda real rejeita espaço codificado como "+"
        return httpx.Response(400, text='/*{"codigo":400,"mensagem":"The types \'Edm.Boolean\' and \'Edm.String\' are not compatible."}*/')
    if host == "api.bcb.gov.br":
        codigo = int(url.split("bcdata.sgs.")[1].split("/")[0])
        return httpx.Response(200, json=SGS[codigo])
    if host == "www3.bcb.gov.br":
        codigo = int(request.content.decode().split("<item>")[1].split("</item>")[0])
        return httpx.Response(200, text=_soap(codigo))
    if host == "olinda.bcb.gov.br":
        filtro = request.url.params["$filter"]
        nome = filtro.split("Indicador eq '")[1].split("'")[0]
        valores = [{"Indicador": nome, "Data": d, "DataReferencia": "2026", "Mediana": v, "numeroRespondentes": 80, "baseCalculo": 0}
                   for d, v in FOCUS.get(nome, [])]
        return httpx.Response(200, json={"@odata.context": "x", "value": valores})
    if host == "www.tesourotransparente.gov.br":
        return httpx.Response(200, content=TESOURO_CSV.encode("latin-1"))
    if host == "www.anbima.com.br":
        return httpx.Response(200, content=ETTJ_CSV.encode("latin-1"))
    if host == "brapi.dev":
        ticker = url.split("/quote/")[1].split("?")[0]
        if ticker in BRAPI:
            return httpx.Response(200, json=BRAPI[ticker])
        # formato real da brapi sem token para tickers fora da lista gratuita
        return httpx.Response(401, json={"error": True, "message": "Token de autenticação não fornecido", "code": "MISSING_TOKEN"})
    if host == "dados.cvm.gov.br":
        if url.endswith("cad_cia_aberta.csv"):
            return httpx.Response(200, content=CIAS_CSV.encode("latin-1"))
        if "inf_diario_fi_202609" in url:
            return httpx.Response(200, content=_zip("inf_diario_fi_202609.csv", INF_DIARIO_CSV))
        return httpx.Response(404)
    if host == "servicodados.ibge.gov.br":
        return httpx.Response(200, content=json.dumps(IBGE).encode())
    return httpx.Response(503)
