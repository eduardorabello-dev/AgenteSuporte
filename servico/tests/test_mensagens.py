import json

import pytest
from fastapi.testclient import TestClient

from suporte.config import CONHECIMENTO
from suporte.contas import ContasTecnicos
from suporte.main import criar_app
from suporte.motor import Motor
from tests.conftest import chat_web

PROBLEMAS = json.loads((CONHECIMENTO / "problemas-comuns.json").read_text(encoding="utf-8"))
FRASES = [(p["texto"], p["artigo"]) for g in PROBLEMAS["grupos"] for p in g["problemas"]]


@pytest.mark.parametrize("frase, artigo", FRASES)
def test_cada_problema_comum_encontra_o_artigo_certo(cfg, frase, artigo):
    r = Motor(cfg).atendimento().processar({"id": "x", "email": "", "descricao": frase})
    assert r["artigos_utilizados"][:1] == [artigo]


def test_problemas_comuns_para_o_chat(cfg):
    grupos = TestClient(criar_app(cfg)).get("/chat/problemas-comuns").json()["grupos"]
    textos = [p["texto"] for g in grupos for p in g["problemas"]]
    assert len(textos) == len(FRASES) >= 15
    assert any(p["destaque"] for g in grupos for p in g["problemas"])


@pytest.fixture
def ambiente(cfg):
    senha = ContasTecnicos(cfg.tecnicos).adicionar("admin.xxxxx7@teste.com", "XXXXX", "admin")
    cliente = TestClient(criar_app(cfg))
    sessao, _ = chat_web(cliente, cfg, "a vpn não conecta de casa")
    protocolo = cliente.post("/chat", json={"sessao": sessao, "mensagem": "não resolveu"}).json()["detalhes"]["protocolo"]
    cliente.post("/tecnico/entrar", json={"email": "admin.xxxxx7@teste.com", "senha": senha})
    cliente.post("/tecnico/senha", json={"atual": senha, "nova": "Xxxxx2026abc"})
    return cliente, sessao, protocolo


def test_conversa_entre_tecnico_e_usuario(ambiente):
    cliente, sessao, protocolo = ambiente
    base = f"/tecnico/chamados/{protocolo}/conversa"

    [c] = cliente.get("/tecnico/chamados").json()["chamados"]
    assert "sessao" not in c
    cliente.get("/chat/mensagens", params={"sessao": sessao})
    chat = cliente.get("/tecnico/chamados").json()["chamados"][0]["chat"]
    assert chat["disponivel"] and chat["online"] and not chat["ativa"]

    assert cliente.post(f"{base}/mensagem", json={"texto": "oi"}).status_code == 409
    r = cliente.post(base).json()
    assert r["tecnico"] == "XXXXX" and r["mensagens"][0]["autor"] == "sistema"
    c = cliente.get("/tecnico/chamados").json()["chamados"][0]
    assert c["status"] == "Em atendimento" and c["tecnico"] == "admin.xxxxx7@teste.com"

    cliente.post(f"{base}/digitando")
    chat = cliente.get("/chat/mensagens", params={"sessao": sessao}).json()
    assert chat["conversa"] == {"protocolo": protocolo, "tecnico": "XXXXX"} and chat["tecnico_digitando"]
    m = cliente.post(f"{base}/mensagem", json={"texto": "Olá! Vou te ajudar com a VPN."}).json()
    chat = cliente.get("/chat/mensagens", params={"sessao": sessao, "desde": m["id"] - 1}).json()
    assert [x["texto"] for x in chat["mensagens"]] == ["Olá! Vou te ajudar com a VPN."]
    assert not chat["tecnico_digitando"]

    cliente.post("/chat/digitando", json={"sessao": sessao})
    assert cliente.get(base).json()["usuario_digitando"]
    r = cliente.post("/chat", json={"sessao": sessao, "mensagem": "Obrigado, continua sem conectar"}).json()
    assert r["detalhes"]["tipo"] == "para_tecnico" and r["texto"] == ""
    ultima = cliente.get(base).json()["mensagens"][-1]
    assert (ultima["autor"], ultima["texto"]) == ("usuario", "Obrigado, continua sem conectar")
    assert cliente.get("/tecnico/chamados").json()["chamados"][0]["chat"]["ultima_do_usuario"] == ultima["id"]

    cliente.post(f"{base}/encerrar")
    chat = cliente.get("/chat/mensagens", params={"sessao": sessao}).json()
    assert chat["conversa"] is None and "encerrou a conversa" in chat["mensagens"][-1]["texto"]
    assert cliente.post("/chat", json={"sessao": sessao, "mensagem": "a impressora não imprime"}).json()[
        "detalhes"]["tipo"] == "atendimento"


def test_historico_fica_no_csv(ambiente, cfg):
    cliente, _, protocolo = ambiente
    cliente.post(f"/tecnico/chamados/{protocolo}/conversa")
    cliente.post(f"/tecnico/chamados/{protocolo}/conversa/mensagem", json={"texto": "Teste de histórico"})
    conteudo = cfg.mensagens.read_text(encoding="utf-8-sig")
    assert "Teste de histórico" in conteudo and protocolo in conteudo


def test_nao_inicia_se_o_chat_da_pessoa_fechou(cfg):
    senha = ContasTecnicos(cfg.tecnicos).adicionar("admin.xxxxx8@teste.com", "XXXXX")
    cliente = TestClient(criar_app(cfg))
    Motor(cfg).registro.registrar({"protocolo": "CH-antigo", "urgencia": "Alta", "sessao": "sessao-que-nao-existe"})
    cliente.post("/tecnico/entrar", json={"email": "admin.xxxxx8@teste.com", "senha": senha})
    cliente.post("/tecnico/senha", json={"atual": senha, "nova": "Xxxxx2026xy"})
    assert cliente.get("/tecnico/chamados").json()["chamados"][0]["chat"]["disponivel"] is False
    assert cliente.post("/tecnico/chamados/CH-antigo/conversa").status_code == 409
    assert cliente.get("/tecnico/chamados/CH-antigo/conversa").status_code == 200
    assert cliente.get("/tecnico/chamados/CH-nada/conversa").status_code == 404


def test_conversa_exige_login(cfg):
    cliente = TestClient(criar_app(cfg))
    assert cliente.post("/tecnico/chamados/CH-1/conversa").status_code == 401
    assert cliente.get("/tecnico/chamados/CH-1/conversa").status_code == 401
