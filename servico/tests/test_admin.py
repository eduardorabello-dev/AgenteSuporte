from datetime import datetime

from fastapi.testclient import TestClient

from suporte.contas import Contas
from suporte.conversa import Conversa
from suporte.estatisticas import indicadores
from suporte.main import criar_app
from suporte.motor import Motor
from tests.conftest import chat_web, sessao_com_email


def entrar_tecnico(cliente, cfg, email, nome, admin):
    contas = Contas(cfg.tecnicos)
    provisoria = contas.adicionar(email, nome, "admin" if admin else "tecnico")
    cliente.post("/tecnico/entrar", json={"email": email, "senha": provisoria})
    cliente.post("/tecnico/senha", json={"atual": provisoria, "nova": "Painel2026xy"})


def test_area_do_admin_so_para_administradores(cfg):
    app = criar_app(cfg)
    admin, tecnico, anonimo = TestClient(app), TestClient(app), TestClient(app)
    entrar_tecnico(admin, cfg, "admin.xxxxx7@teste.com", "XXXXX", admin=True)
    entrar_tecnico(tecnico, cfg, "xxxxx6@teste.com", "XXXXX", admin=False)
    for caminho in ("/tecnico/admin/indicadores", "/tecnico/admin/contas"):
        assert anonimo.get(caminho).status_code == 401
        assert tecnico.get(caminho).status_code == 403
        assert admin.get(caminho).status_code == 200
    assert tecnico.post("/tecnico/admin/contas", json={"tipo": "colaborador", "email": "x@teste.com",
                                                        "nome": "X"}).status_code == 403


def test_admin_gerencia_contas(cfg):
    cliente = TestClient(criar_app(cfg))
    entrar_tecnico(cliente, cfg, "admin.xxxxx7@teste.com", "XXXXX", admin=True)

    r = cliente.post("/tecnico/admin/contas", json={"tipo": "colaborador", "email": "XXXXX6@Teste.com", "nome": "XXXXX"})
    assert r.status_code == 200 and r.json()["senha_provisoria"].startswith("Prov-")
    provisoria = r.json()["senha_provisoria"]
    assert cliente.post("/tecnico/admin/contas", json={"tipo": "colaborador", "email": "xxxxx6@teste.com",
                                                        "nome": "XXXXX"}).status_code == 422
    r = cliente.post("/tecnico/admin/contas", json={"tipo": "tecnico", "email": "xxxxx4@teste.com", "nome": "XXXXX", "admin": True})
    assert r.status_code == 200

    lista = cliente.get("/tecnico/admin/contas").json()
    xxxxx6 = next(c for c in lista["colaboradores"] if c["email"] == "xxxxx6@teste.com")
    assert xxxxx6["senha_provisoria"] and xxxxx6["ativo"] and "hash" not in xxxxx6 and "sal" not in xxxxx6
    assert any(c["email"] == "xxxxx4@teste.com" and c["papel"] == "admin" for c in lista["tecnicos"])

    chat = cliente
    chat.post("/chat/entrar", json={"email": "xxxxx6@teste.com", "senha": provisoria})
    assert cliente.post("/tecnico/admin/contas/ativo", json={"tipo": "colaborador", "email": "xxxxx6@teste.com",
                                                             "ativo": False}).status_code == 200
    assert chat.get("/chat/eu").status_code == 401
    assert chat.post("/chat/entrar", json={"email": "xxxxx6@teste.com", "senha": provisoria}).status_code == 401

    nova = cliente.post("/tecnico/admin/contas/redefinir", json={"tipo": "colaborador", "email": "xxxxx6@teste.com"}).json()
    cliente.post("/tecnico/admin/contas/ativo", json={"tipo": "colaborador", "email": "xxxxx6@teste.com", "ativo": True})
    assert chat.post("/chat/entrar", json={"email": "xxxxx6@teste.com", "senha": nova["senha_provisoria"]}).status_code == 200

    for rota, corpo in (("ativo", {"ativo": False}), ("redefinir", {})):
        r = cliente.post(f"/tecnico/admin/contas/{rota}", json={"tipo": "tecnico", "email": "admin.xxxxx7@teste.com"} | corpo)
        assert r.status_code == 422
    assert cliente.post("/tecnico/admin/contas/redefinir", json={"tipo": "colaborador", "email": "nao@existe.com"}).status_code == 404


def test_atendimentos_viram_indicadores(cfg):
    motor = Motor(cfg)
    conversa = Conversa(motor)
    s = sessao_com_email(conversa)
    conversa.responder(s, "a vpn não conecta de casa")
    conversa.responder(s, "resolveu")
    conversa.responder(s, "o computador está muito lento")
    conversa.responder(s, "não resolveu")
    conversa.responder(s, "xyzzy blorft")
    s2 = sessao_com_email(conversa, "outro@empresa.com")
    conversa.responder(s2, "a impressora não imprime")

    eventos = motor.atendimentos.listar()
    assert [e["evento"] for e in eventos].count("atendido") == 3
    r = indicadores(eventos, motor.registro.listar(), [], {}, agora=datetime.now())
    assert r["chat"] == {"atendimentos": 3, "resolvidos": 1, "encaminhados": 1, "sem_desfecho": 1, "taxa_resolucao": 50}
    assert r["nao_entendidas"] == [{"texto": "xyzzy blorft", "vezes": 1}]
    assert sum(d["atendimentos"] for d in r["atividade"]) == 3 and len(r["atividade"]) == 14
    categorias = {c["categoria"]: c for c in r["categorias"]}
    assert categorias["Rede/VPN"]["resolvidos"] == 1 and sum(c["encaminhados"] for c in categorias.values()) == 1
    assert r["fila"]["abertos"] == 1 and r["fila"]["sem_responsavel"] == 1


def test_indicadores_de_avaliacoes_e_fila():
    avaliacoes = [{"nota": "5", "solucao": "A"}, {"nota": "4", "solucao": "A"}, {"nota": "1", "solucao": "B"}]
    chamados = [
        {"status": "Concluído", "data": "10/11/2026 10:00", "atualizado_em": "10/11/2026 11:30", "tecnico": "e@t.com",
         "previsao": "10/11/2026 12:00"},
        {"status": "Aberto", "data": "10/11/2026 10:00", "atualizado_em": "", "tecnico": "e@t.com",
         "previsao": "10/11/2026 10:30"},
    ]
    r = indicadores([], chamados, avaliacoes, {"e@t.com": "XXXXX"}, agora=datetime(2026, 11, 10, 12, 0))
    assert r["avaliacoes"]["media"] == 3.3 and r["avaliacoes"]["distribuicao"][4] == {"nota": 5, "quantidade": 1}
    assert r["avaliacoes"]["piores_solucoes"][0] == {"solucao": "B", "media": 1.0, "avaliacoes": 1}
    assert r["fila"]["tempo_medio_minutos"] == 90 and r["fila"]["atrasados"] == 1
    assert r["tecnicos"] == [{"nome": "XXXXX", "abertos": 1, "em_atendimento": 0, "concluidos": 1, "atrasados": 1}]
    assert r["chat"]["taxa_resolucao"] is None


def test_pagina_do_painel_tem_area_admin(cfg):
    cliente = TestClient(criar_app(cfg))
    assert "/arquivos/painel/admin.js" in cliente.get("/tecnico").text
    assert cliente.get("/arquivos/painel/admin.js").status_code == 200
    _, r = chat_web(cliente, cfg, "a vpn não conecta de casa")
    assert r["detalhes"]["tipo"] == "atendimento"
