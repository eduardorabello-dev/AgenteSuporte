import csv
import json

import pytest
from fastapi.testclient import TestClient

from suporte.config import CONHECIMENTO
from suporte.conversa import Conversa
from suporte.main import criar_app
from suporte.motor import Motor
from tests.conftest import chat_web, sessao_com_email
from suporte.registro import CAMPOS, RegistroChamados, descrever_minutos

PRAZOS = {"Crítica": 15, "Alta": 45, "Média": 120, "Baixa": 240}


@pytest.fixture
def registro(tmp_path):
    return RegistroChamados(tmp_path / "encaminhados.csv", PRAZOS, 10)


def test_descrever_minutos():
    assert descrever_minutos(45) == "45 min"
    assert descrever_minutos(60) == "1 h"
    assert descrever_minutos(135) == "2 h 15 min"


def test_previsao_soma_a_fila_de_mesma_urgencia_ou_maior(registro):
    assert registro.estimar("Alta")["minutos"] == 45 and registro.estimar("Alta")["na_frente"] == 0
    registro.registrar({"protocolo": "A", "urgencia": "Crítica"})
    registro.registrar({"protocolo": "B", "urgencia": "Baixa"})
    p = registro.estimar("Alta")
    assert p["na_frente"] == 1 and p["minutos"] == 55
    assert registro.estimar("Baixa")["na_frente"] == 2
    registro.atualizar("A", status="Concluído")
    assert registro.estimar("Alta")["na_frente"] == 0


def test_registrar_e_atualizar(registro):
    previsao = registro.registrar({"protocolo": "CH-1", "email": "x@empresa.com", "urgencia": "Média"})
    [c] = registro.listar()
    assert c["status"] == "Aberto" and c["previsao"] == previsao["ate_data"]
    c = registro.atualizar("CH-1", status="Em atendimento", tecnico="  Marcos ", observacao="liguei para o usuário")
    assert (c["status"], c["tecnico"], c["observacao"]) == ("Em atendimento", "Marcos", "liguei para o usuário")
    assert registro.listar()[0]["tecnico"] == "Marcos"
    with pytest.raises(ValueError):
        registro.atualizar("CH-1", status="Inventado")
    with pytest.raises(KeyError):
        registro.atualizar("CH-nao-existe", status="Aberto")


def test_le_arquivo_antigo_sem_status(tmp_path):
    arquivo = tmp_path / "encaminhados.csv"
    with arquivo.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("data;protocolo;email;descricao;categoria;urgencia;motivo;acoes_executadas\n")
        f.write("09/11/2026 17:37;CH-velho;a@b.com;conta bloqueada;Senha/Acesso;Alta;não resolveu;\n")
    registro = RegistroChamados(arquivo, PRAZOS, 10)
    antigo = registro.listar()[0]
    assert antigo["status"] == "Aberto" and antigo["previsao"] == "09/11/2026 18:22"
    registro.registrar({"protocolo": "CH-novo", "urgencia": "Baixa"})
    with arquivo.open(encoding="utf-8-sig") as f:
        leitor = csv.DictReader(f, delimiter=";")
        assert leitor.fieldnames == CAMPOS
        assert [l["protocolo"] for l in leitor] == ["CH-velho", "CH-novo"]


def test_chat_mostra_previsao_ao_encaminhar(cfg):
    conversa = Conversa(Motor(cfg))
    s = sessao_com_email(conversa)
    conversa.responder(s, "a vpn não conecta de casa")
    r = conversa.responder(s, "não resolveu")
    assert "Previsão para um técnico te chamar" in r["texto"]
    assert r["detalhes"]["previsao"]["minutos"] >= 45
    assert "previsão de contato" in conversa.responder(s, "não resolveu")["texto"]


def test_diretorio_real_vazio():
    assert json.loads((CONHECIMENTO / "usuarios-mock.json").read_text(encoding="utf-8")) == []


def test_distribui_para_o_tecnico_menos_ocupado(registro):
    equipe = ["xxxxx7@t.com", "xxxxx8@t.com"]
    assert registro.registrar({"protocolo": "1", "urgencia": "Alta"}, equipe)["tecnico"] == "xxxxx7@t.com"
    assert registro.registrar({"protocolo": "2", "urgencia": "Alta"}, equipe)["tecnico"] == "xxxxx8@t.com"
    p3 = registro.registrar({"protocolo": "3", "urgencia": "Alta"}, equipe)
    assert p3["tecnico"] == "xxxxx7@t.com" and p3["na_frente"] == 1
    registro.atualizar("1", status="Concluído")
    registro.atualizar("3", status="Concluído")
    assert registro.registrar({"protocolo": "4", "urgencia": "Baixa"}, equipe)["tecnico"] == "xxxxx7@t.com"


def test_distribuir_chamados_sem_responsavel(registro):
    for i in range(3):
        registro.registrar({"protocolo": str(i), "urgencia": "Média"})
    registro.atualizar("2", tecnico="Fulano de antes")
    assert {c["tecnico"] for c in registro.listar()} == {"", "Fulano de antes"}
    assert registro.distribuir(["a@t.com", "b@t.com"], por="a@t.com") == 3
    donos = [c["tecnico"] for c in registro.listar()]
    assert sorted(donos) == ["a@t.com", "a@t.com", "b@t.com"]
    assert registro.listar()[0]["atualizado_por"] == "a@t.com"


def entrar(cliente, email, senha):
    return cliente.post("/tecnico/entrar", json={"email": email, "senha": senha})


def test_painel_exige_login_e_troca_da_senha_provisoria(cfg):
    from suporte.contas import ContasTecnicos
    senha = ContasTecnicos(cfg.tecnicos).adicionar("Admin.XXXXX7@teste.com", "XXXXX", "admin")
    cliente = TestClient(criar_app(cfg))
    assert "Painel do Técnico" in cliente.get("/tecnico").text
    assert cliente.get("/tecnico/chamados").status_code == 401
    assert entrar(cliente, "admin.xxxxx7@teste.com", "errada").status_code == 401

    r = entrar(cliente, "ADMIN.XXXXX7@teste.com", senha)
    assert r.status_code == 200 and r.json()["trocar_senha"] is True and r.json()["nome"] == "XXXXX"
    assert cliente.get("/tecnico/chamados").status_code == 403
    assert cliente.post("/tecnico/senha", json={"atual": senha, "nova": "curta1"}).status_code == 422
    assert cliente.post("/tecnico/senha", json={"atual": "errada", "nova": "NovaSenha2026"}).status_code == 401
    r = cliente.post("/tecnico/senha", json={"atual": senha, "nova": "NovaSenha2026"})
    assert r.status_code == 200 and r.json()["trocar_senha"] is False
    assert cliente.get("/tecnico/chamados").status_code == 200

    outro = TestClient(criar_app(cfg))
    assert entrar(outro, "admin.xxxxx7@teste.com", senha).status_code == 401
    assert entrar(outro, "admin.xxxxx7@teste.com", "NovaSenha2026").json()["trocar_senha"] is False

    cliente.post("/tecnico/sair")
    assert cliente.get("/tecnico/chamados").status_code == 401


def test_login_bloqueia_depois_de_varias_tentativas(cfg):
    from suporte.contas import ContasTecnicos
    ContasTecnicos(cfg.tecnicos).adicionar("xxxxx8@teste.com", "XXXXX")
    cliente = TestClient(criar_app(cfg))
    for _ in range(5):
        assert entrar(cliente, "xxxxx8@teste.com", "errada").status_code == 401
    assert entrar(cliente, "xxxxx8@teste.com", "errada").status_code == 429


def test_redefinir_senha_derruba_sessao(cfg):
    from suporte.contas import ContasTecnicos
    contas = ContasTecnicos(cfg.tecnicos)
    senha = contas.adicionar("xxxxx8@teste.com", "XXXXX")
    cliente = TestClient(criar_app(cfg))
    entrar(cliente, "xxxxx8@teste.com", senha)
    cliente.post("/tecnico/senha", json={"atual": senha, "nova": "Outra2026x"})
    assert cliente.get("/tecnico/chamados").status_code == 200
    contas.redefinir("xxxxx8@teste.com")
    assert cliente.get("/tecnico/chamados").status_code == 401


def test_chamados_separados_por_tecnico(cfg):
    from suporte.contas import ContasTecnicos
    contas = ContasTecnicos(cfg.tecnicos)
    senha_e = contas.adicionar("admin.xxxxx7@teste.com", "XXXXX", "admin")
    contas.adicionar("admin.xxxxx8@teste.com", "XXXXX", "admin")
    cliente = TestClient(criar_app(cfg))
    for problema in ("a vpn não conecta de casa", "a impressora não imprime, fica na fila"):
        sessao, _ = chat_web(cliente, cfg, problema)
        r = cliente.post("/chat", json={"sessao": sessao, "mensagem": "não resolveu"}).json()
        assert r["detalhes"]["previsao"]["tecnico"] in {"XXXXX", "XXXXX"}
        assert "Técnico responsável" in r["texto"]

    entrar(cliente, "admin.xxxxx7@teste.com", senha_e)
    cliente.post("/tecnico/senha", json={"atual": senha_e, "nova": "Xxxxx2026abc"})
    corpo = cliente.get("/tecnico/chamados").json()
    assert {t["email"] for t in corpo["equipe"]} == {"admin.xxxxx7@teste.com", "admin.xxxxx8@teste.com"}
    assert sorted(c["tecnico"] for c in corpo["chamados"]) == ["admin.xxxxx7@teste.com", "admin.xxxxx8@teste.com"]
    do_xxxxx8 = next(c for c in corpo["chamados"] if c["tecnico"] == "admin.xxxxx8@teste.com")

    r = cliente.patch(f"/tecnico/chamados/{do_xxxxx8['protocolo']}",
                      json={"tecnico": "admin.xxxxx7@teste.com", "status": "Em atendimento"})
    assert r.status_code == 200 and r.json()["atualizado_por"] == "admin.xxxxx7@teste.com"
    assert cliente.patch(f"/tecnico/chamados/{do_xxxxx8['protocolo']}", json={"tecnico": "x@y.com"}).status_code == 422
    assert cliente.patch(f"/tecnico/chamados/{do_xxxxx8['protocolo']}", json={"status": "xyz"}).status_code == 422
    assert cliente.patch("/tecnico/chamados/CH-nada", json={"status": "Aberto"}).status_code == 404


def test_senha_nao_fica_em_texto(cfg):
    from suporte.contas import ContasTecnicos
    senha = ContasTecnicos(cfg.tecnicos).adicionar("xxxxx8@teste.com", "XXXXX")
    conteudo = cfg.tecnicos.read_text(encoding="utf-8")
    assert senha not in conteudo and '"senha_provisoria": true' in conteudo
