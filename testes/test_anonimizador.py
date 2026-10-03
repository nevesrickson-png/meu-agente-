import pytest

from quiron.nucleo.anonimizador import Anonimizador, anonimizar, cnpj_valido, cpf_valido

# CPF/CNPJ de exemplo com dígitos verificadores válidos (gerados para teste, não pertencem a ninguém)
CPF = "529.982.247-25"
CNPJ = "11.222.333/0001-81"


def test_validacao_de_documentos():
    assert cpf_valido(CPF) and cpf_valido("52998224725")
    assert not cpf_valido("529.982.247-26") and not cpf_valido("111.111.111-11")
    assert cnpj_valido(CNPJ) and cnpj_valido("11222333000181")
    assert not cnpj_valido("11.222.333/0001-80")


@pytest.mark.parametrize(
    "texto, tipo",
    [
        (f"CPF do cliente: {CPF}", "CPF"),
        ("cpf 52998224725 informado", "CPF"),
        (f"empresa {CNPJ}", "CNPJ"),
        ("CNPJ 11222333000181", "CNPJ"),
        ("mande para joao.silva+inv@gmail.com amanhã", "EMAIL"),
        ("ligar no (11) 98765-4321", "TELEFONE"),
        ("whats +55 11 98765-4321", "TELEFONE"),
        ("fixo 11 3456-7890", "TELEFONE"),
        ("cel 11987654321", "TELEFONE"),
        ("RG: 12.345.678-9", "RG"),
        ("mora no CEP 01310-100", "CEP"),
    ],
)
def test_documentos_e_contatos(texto, tipo):
    saida = anonimizar(texto)
    assert f"[{tipo}_1]" in saida, saida


@pytest.mark.parametrize(
    "texto, nome",
    [
        ("Reunião com o cliente Fulgêncio Andrade amanhã", "Fulgêncio Andrade"),
        ("A Sra. Odete Pires quer previdência", "Odete Pires"),
        ("Dr. Hermes Batista pediu revisão", "Hermes Batista"),
        ("Maria Aparecida de Souza tem 2 milhões em CDB", "Maria Aparecida de Souza"),
        ("falei com João Pedro Lima ontem", "João Pedro Lima"),
        ("a esposa Clotilde aprovou", "Clotilde"),
    ],
)
def test_nomes(texto, nome):
    saida = anonimizar(texto)
    assert nome not in saida and "[NOME_1]" in saida, saida


def test_nomes_protegidos_cadastrados():
    saida = anonimizar("O Zebedeu Quintanilha ligou", ["Zebedeu Quintanilha"])
    assert saida == "O [NOME_1] ligou"


def test_preserva_termos_de_mercado_e_codigos():
    texto = (
        "CLI-012 tem R$ 1.250.000,00 no Tesouro Direto IPCA+ 2035 e 30% em PETR4; "
        "Selic em 15,00% segundo o Banco Central em 03/10/2026. Duration de 4,5 anos."
    )
    assert anonimizar(texto) == texto


def test_mesmo_valor_mesmo_marcador_e_reversao():
    anon = Anonimizador()
    original = f"cliente Odete Pires, CPF {CPF}. Confirmar com Odete Pires o CPF {CPF}."
    saida = anon.anonimizar(original)
    assert saida.count("[NOME_1]") == 2 and saida.count("[CPF_1]") == 2
    assert "Odete" not in saida and "529" not in saida
    resposta_modelo = "Sugiro ligar para [NOME_1] e conferir o documento [CPF_1]."
    assert anon.desanonimizar(resposta_modelo) == f"Sugiro ligar para Odete Pires e conferir o documento {CPF}."


def test_texto_vazio():
    assert anonimizar("") == ""


def test_nome_detectado_vale_para_o_texto_todo():
    saida = anonimizar("A Sra. Odete Pires ligou. Odete quer resgatar; Pires é o sobrenome do marido.")
    assert "Odete" not in saida and "Pires" not in saida, saida
