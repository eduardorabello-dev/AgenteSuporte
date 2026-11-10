import json

from fastapi.testclient import TestClient

from suporte.contas import ContasTecnicos
from suporte.conversa import Conversa
from suporte.main import criar_app
from suporte.motor import Motor
from tests.conftest import chat_web, sessao_com_email


def historico_do_chamado(motor, protocolo):
    linha = next(c for c in motor.registro.listar() if c["protocolo"] == protocolo)
    return json.loads(linha["historico_chat"])


def test_historico_vai_para_o_chamado_com_passos_feitos(cfg):
    motor = Motor(cfg)
    conversa = Conversa(motor)
    s = sessao_com_email(conversa)
    d = conversa.responder(s, "a vpn não conecta de casa")["detalhes"]
    titulo, total = d["passos"]["titulo"], len(d["passos"]["itens"])
    assert conversa.marcar_passos(s, titulo, [0, 2, 99])
    protocolo = conversa.responder(s, "não resolveu")["detalhes"]["protocolo"]

    eventos = historico_do_chamado(motor, protocolo)
    assert [e["tipo"] for e in eventos] == ["mensagem", "solucao", "mensagem"]
    assert eventos[0]["texto"] == "a vpn não conecta de casa" and eventos[2]["texto"] == "não resolveu"
    assert eventos[1]["titulo"] == titulo and eventos[1]["feitos"] == [0, 2] and len(eventos[1]["passos"]) == total

    conversa.marcar_passos(s, titulo, [0, 1, 2])
    assert historico_do_chamado(motor, protocolo)[1]["feitos"] == [0, 1, 2]

    conversa.responder(s, "outro problema")
    conversa.responder(s, "a impressora não imprime")
    assert len(historico_do_chamado(motor, protocolo)) == 3
    assert [e["tipo"] for e in s.historico] == ["mensagem", "solucao"]


def test_problema_novo_sem_dizer_outro_problema_nao_vaza_para_o_chamado_antigo(cfg):
    motor = Motor(cfg)
    conversa = Conversa(motor)
    s = sessao_com_email(conversa)
    conversa.responder(s, "a vpn não conecta de casa")
    protocolo = conversa.responder(s, "não resolveu")["detalhes"]["protocolo"]
    conversa.responder(s, "a impressora não imprime")
    assert [e.get("texto") for e in historico_do_chamado(motor, protocolo) if e["tipo"] == "mensagem"] == [
        "a vpn não conecta de casa", "não resolveu"]


def test_painel_recebe_o_historico_e_o_chat_marca_passos(cfg):
    senha = ContasTecnicos(cfg.tecnicos).adicionar("admin.xxxxx7@teste.com", "XXXXX", "admin")
    cliente = TestClient(criar_app(cfg))
    sessao, r = chat_web(cliente, cfg, "o computador está muito lento")
    titulo = r["detalhes"]["passos"]["titulo"]
    assert cliente.post("/chat/passos", json={"sessao": sessao, "titulo": titulo, "feitos": [1]}).json()["ok"]
    assert cliente.post("/chat/passos", json={"sessao": "nao-existe", "titulo": titulo, "feitos": [1]}).status_code == 404
    cliente.post("/chat", json={"sessao": sessao, "mensagem": "não resolveu"})

    cliente.post("/tecnico/entrar", json={"email": "admin.xxxxx7@teste.com", "senha": senha})
    cliente.post("/tecnico/senha", json={"atual": senha, "nova": "Xxxxx2026abc"})
    [c] = cliente.get("/tecnico/chamados").json()["chamados"]
    assert "historico_chat" not in c and "sessao" not in c
    solucao = next(e for e in c["historico"] if e["tipo"] == "solucao")
    assert solucao["titulo"] == titulo and solucao["feitos"] == [1]


def test_descricao_sem_as_sobras_do_email(cfg):
    conversa = Conversa(Motor(cfg))
    for frase, esperado in [
        ("sou xxxxx4@empresa.com e o Outlook não envia nem recebe e-mails", "o Outlook não envia nem recebe e-mails"),
        ("meu e-mail é xxxxx4@empresa.com, a vpn não conecta de casa", "a vpn não conecta de casa"),
        ("e-mail não abre, sou xxxxx4@empresa.com", "e-mail não abre, sou"),
    ]:
        s = conversa.sessao(None)
        conversa.responder(s, frase)
        assert s.ultima_descricao == esperado, frase


def test_tecnico_fala_com_a_pessoa_na_sessao_mais_recente_dela(cfg):
    conversa = Conversa(Motor(cfg))
    antiga = conversa.sessao_da_conta(None, "xxxxx1@teste.com", "XXXXX")
    nova = conversa.sessao_da_conta(None, "xxxxx1@teste.com", "XXXXX")
    conversa.sessao_da_conta(None, "xxxxx2@teste.com", "XXXXX")
    assert antiga.id != nova.id and antiga.email_fixo and nova.nome == "XXXXX"
    achada = conversa.sessao_do_email("xxxxx1@teste.com")
    assert achada is not None and achada.id == nova.id
    assert conversa.sessao_do_email("ninguem@teste.com") is None


def test_colaborador_registrado_e_atualizado(cfg):
    motor = Motor(cfg)
    conversa = Conversa(motor)
    s1 = conversa.sessao(None)
    conversa.responder(s1, "xxxxx2@empresa.com")
    conversa.responder(s1, "xxxxx2@empresa.com")
    [c] = motor.colaboradores.listar()
    assert (c["email"], c["nome"], c["atendimentos"], c["chamados_encaminhados"]) == (
        "xxxxx2@empresa.com", "XXXXX", "1", "0")

    s2 = conversa.sessao(None)
    conversa.responder(s2, "sou XXXXX2@empresa.com e a vpn não conecta de casa")
    protocolo = conversa.responder(s2, "não resolveu")["detalhes"]["protocolo"]
    conversa.responder(conversa.sessao(None), "xxxxx1@empresa.com")

    linhas = {l["email"]: l for l in motor.colaboradores.listar()}
    assert set(linhas) == {"xxxxx2@empresa.com", "xxxxx1@empresa.com"}
    xxxxx2 = linhas["xxxxx2@empresa.com"]
    assert xxxxx2["atendimentos"] == "2" and xxxxx2["chamados_encaminhados"] == "1"
    assert xxxxx2["ultimo_protocolo"] == protocolo and xxxxx2["primeiro_contato"]
    assert cfg.colaboradores.read_text(encoding="utf-8-sig").startswith("email;nome;primeiro_contato")
