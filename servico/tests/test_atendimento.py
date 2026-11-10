import pytest

from suporte.diretorio import DiretorioMock
from suporte.motor import Motor, PlanilhaIndisponivel


@pytest.fixture
def motor(cfg):
    return Motor(cfg)


def atender(motor, **campos):
    return motor.atendimento().processar({"id": "T1", "nome": "Fulano de Tal", "email": "", **campos})


def test_diretorio_mock_senhas(cfg):
    d = DiretorioMock(cfg.usuarios_mock)
    xxxxx1, xxxxx2, xxxxx5 = (d.obter_senha(e) for e in
                         ("xxxxx1@empresa.com", "XXXXX2@empresa.com ", "xxxxx5@empresa.com"))
    assert xxxxx1 is not None and xxxxx2 is not None and xxxxx5 is not None
    assert xxxxx1["expirada"] is False and 1 <= xxxxx1["dias_restantes"] <= 3
    assert xxxxx2["expirada"] is True and xxxxx2["dias_restantes"] < 0
    assert xxxxx5["nunca_expira"] is True and xxxxx5["senha_expira_em"] is None
    assert d.obter_status("x@empresa.com") is None


def test_somente_triagem(motor):
    r = motor.atendimento().processar({"descricao": "Não consigo conectar na VPN de casa"}, somente_triagem=True)
    assert r["categoria"] == "Rede/VPN" and "resposta_usuario" not in r


def test_conta_bloqueada_e_desbloqueada(motor):
    r = atender(motor, nome="XXXXX", email="xxxxx3@empresa.com",
                assunto="Conta bloqueada", descricao="Errei a senha várias vezes e minha conta está bloqueada")
    assert r["categoria"] == "Senha/Acesso"
    assert any(a["acao"] == "desbloquear conta" and "sucesso" in a["resultado"] for a in r["acoes_executadas"])
    assert r["escalar_para_humano"] is False and r["resolvido_automaticamente"] is True
    assert r["resposta_usuario"].startswith("Olá, XXXXX!")
    status = motor.diretorio.obter_status("xxxxx3@empresa.com")
    assert status is not None and status["bloqueada"] is False


def test_senha_expirada_informa_data_e_passos(motor):
    r = atender(motor, nome="XXXXX", email="xxxxx2@empresa.com",
                descricao="Minha senha expirou e não consigo entrar no Windows")
    assert "Sua senha expirou em" in r["resposta_usuario"]
    assert r["artigos_utilizados"][0] == "KB-001"
    assert not any(a["acao"] == "desbloquear conta" for a in r["acoes_executadas"])


def test_phishing_escala_e_nao_mexe_na_conta(motor):
    r = atender(motor, nome="XXXXX", email="xxxxx3@empresa.com",
                descricao="Cliquei num link suspeito de um email e digitei minha senha, agora a conta está bloqueada")
    assert r["incidente_seguranca"] is True and r["escalar_para_humano"] is True
    assert not any(a["acao"] == "desbloquear conta" for a in r["acoes_executadas"])


def test_conta_desabilitada_escala(motor):
    r = atender(motor, email="xxxxx5@empresa.com", descricao="Minha conta está bloqueada, não consigo entrar")
    assert r["escalar_para_humano"] is True and "desabilitada" in r["motivo_escalonamento"]


def test_usuario_desconhecido_escala(motor):
    r = atender(motor, email="ninguem@empresa.com", descricao="Minha senha expirou")
    assert r["escalar_para_humano"] is True and "não foi encontrado" in r["motivo_escalonamento"]


def test_critica_escala(motor):
    r = atender(motor, descricao="A internet do setor caiu e ninguém consegue trabalhar")
    assert r["urgencia"] == "Crítica" and r["escalar_para_humano"] is True


def test_sem_artigo_escala(motor):
    r = atender(motor, descricao="Quero trocar a cor da parede da sala")
    assert r["artigos_utilizados"] == [] and r["escalar_para_humano"] is True


def test_planilha_inexistente(cfg, tmp_path):
    from dataclasses import replace

    with pytest.raises(PlanilhaIndisponivel, match="não encontrada"):
        Motor(replace(cfg, planilha=tmp_path / "nao-existe.xlsx")).atendimento()
