import pytest

from suporte.base_conhecimento import BaseConhecimento
from suporte.config import CONHECIMENTO
from suporte.texto import Analisador


@pytest.fixture(scope="module")
def kb():
    return BaseConhecimento(CONHECIMENTO / "base-conhecimento.json", Analisador(CONHECIMENTO / "sinonimos.json"))


def primeiro(kb, consulta, categoria=None):
    artigos = kb.buscar(consulta, categoria)["artigos"]
    return artigos[0]["id"] if artigos else None


@pytest.mark.parametrize("consulta, esperado", [
    ("senha expirou não consigo logar", "KB-001"),
    ("minha conta bloqueou", "KB-002"),
    ("vpn não conecta", "KB-003"),
    ("cliquei num link suspeito", "KB-008"),
    ("headset sem áudio", "KB-009"),
    ("ramal indisponível softphone", "KB-010"),
    ("mouse parou de funcionar", "KB-015"),
    ("papel enroscado impressora", "KB-005"),
])
def test_artigo_certo_em_primeiro(kb, consulta, esperado):
    assert primeiro(kb, consulta) == esperado


@pytest.mark.parametrize("consulta, esperado", [
    ("meu fone não funciona", "KB-009"),
    ("o pc está travando muito", "KB-007"),
    ("não consigo logar, a conta travou", "KB-002"),
    ("recebi um golpe por correio eletrônico", "KB-008"),
])
def test_sinonimos(kb, consulta, esperado):
    assert primeiro(kb, consulta) == esperado


@pytest.mark.parametrize("consulta, esperado", [
    ("impresora nao imprimi", "KB-005"),
    ("minha conta esta bloqeada", "KB-002"),
    ("heaset sem audio", "KB-009"),
])
def test_corrige_erros_de_digitacao(kb, consulta, esperado):
    resultado = kb.buscar(consulta)
    assert resultado["correcoes"], "deveria ter corrigido algum termo"
    assert resultado["artigos"][0]["id"] == esperado


def test_explica_termos_encontrados(kb):
    artigo = kb.buscar("toner da impressora acabou")["artigos"][0]
    assert artigo["id"] == "KB-005"
    assert "toner" in artigo["termos_encontrados"]


def test_sem_termos_relevantes_nao_retorna_nada(kb):
    assert kb.buscar("preciso de ajuda")["artigos"] == []
    assert kb.buscar("receita de bolo de cenoura")["artigos"] == []


def test_limita_a_tres_artigos(kb):
    assert len(kb.buscar("senha outlook vpn impressora email")["artigos"]) <= 3
