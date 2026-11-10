import csv

import pytest
from fastapi.testclient import TestClient

from suporte.conversa import Conversa
from suporte.main import criar_app
from suporte.motor import Motor
from tests.conftest import chat_web, entrar_no_chat, sessao_com_email


@pytest.fixture
def conversa(cfg):
    return Conversa(Motor(cfg))


def falar(conversa, sessao, *mensagens):
    return [conversa.responder(sessao, m) for m in mensagens][-1]


def test_saudacao_e_ajuda(conversa):
    s = conversa.sessao(None)
    assert "Em que posso ajudar" in falar(conversa, s, "oi, tudo bem?")["texto"]
    assert "Descreva o problema" in falar(conversa, s, "ajuda")["texto"]


def test_pede_email_e_desbloqueia(conversa):
    s = conversa.sessao(None)
    r = falar(conversa, s, "minha conta está bloqueada, não consigo entrar")
    assert "e-mail corporativo" in r["texto"]
    r = falar(conversa, s, "xxxxx3@empresa.com")
    assert "Conta desbloqueada com sucesso" in r["texto"]
    assert r["detalhes"]["categoria"] == "Senha/Acesso"
    assert s.nome == "XXXXX"


def test_email_junto_com_o_problema(conversa):
    s = conversa.sessao(None)
    r = falar(conversa, s, "sou xxxxx2@empresa.com e minha senha expirou")
    assert "Sua senha expirou em" in r["texto"]


def test_sempre_pede_email_antes_de_atender(conversa):
    for problema in ("a impresora nao imprime, fica na fila", "o Teams não abre e dá erro", "o pc tá lento"):
        s = conversa.sessao(None)
        r = falar(conversa, s, problema)
        assert r["detalhes"] == {"tipo": "pedir_email"} and "e-mail corporativo" in r["texto"], problema
        assert s.ultimo is None and s.pendente == problema


def test_insiste_no_email_sem_perder_o_problema(conversa):
    s = conversa.sessao(None)
    falar(conversa, s, "a impresora nao imprime, fica na fila")
    r = falar(conversa, s, "não sei meu email")
    assert r["detalhes"] == {"tipo": "pedir_email"} and "Preciso do seu" in r["texto"]
    assert falar(conversa, s, "resolveu")["detalhes"] == {"tipo": "pedir_email"}
    r = falar(conversa, s, "xxxxx4@empresa.com")
    assert r["detalhes"]["categoria"] == "Impressora"
    assert "\"impresora\" como \"impressora\"" in r["texto"]
    assert s.ultima_descricao.startswith("a impresora nao imprime, fica na fila")


def test_resolveu_fecha(conversa):
    s = sessao_com_email(conversa)
    falar(conversa, s, "a vpn não conecta de casa")
    assert "Que bom" in falar(conversa, s, "resolveu, obrigado")["texto"]
    assert s.ultimo is None


def test_nao_resolveu_registra_para_tecnico(conversa, cfg):
    s = sessao_com_email(conversa)
    falar(conversa, s, "a vpn não conecta de casa")
    r = falar(conversa, s, "não resolveu")
    assert "Registrei seu chamado" in r["texto"] and r["detalhes"]["encaminhado"]
    with cfg.encaminhados.open(encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    assert len(linhas) == 1
    assert linhas[0]["descricao"] == "a vpn não conecta de casa"
    assert linhas[0]["motivo"] == "a solução sugerida não resolveu"


def test_seguranca_registra_direto_e_nao_duplica(conversa, cfg):
    s = conversa.sessao(None)
    r = falar(conversa, s, "xxxxx1@empresa.com", "cliquei num link suspeito e digitei minha senha")
    assert "registrei seu chamado para a equipe técnica" in r["texto"]
    assert "já está registrado" in falar(conversa, s, "não resolveu")["texto"]
    with cfg.encaminhados.open(encoding="utf-8-sig") as f:
        assert len(list(csv.DictReader(f, delimiter=";"))) == 1


def test_outlook_pedindo_senha_nao_e_golpe(conversa):
    regras = conversa.motor.regras
    assert not regras.incidente_seguranca("minha senha expirou e o outlook fica pedindo senha")
    assert regras.incidente_seguranca("recebi um e-mail do banco pedindo minha senha")


def test_outro_artigo_por_numero(conversa):
    s = conversa.sessao(None)
    r = falar(conversa, s, "xxxxx1@empresa.com", "minha senha expirou e o outlook fica pedindo senha")
    assert "digite o número" in r["texto"]
    r2 = falar(conversa, s, "2")
    assert "Isso resolveu?" in r2["texto"]
    assert "Não tenho a opção" in falar(conversa, s, "9")["texto"]


def test_texto_sem_sentido(conversa):
    s = sessao_com_email(conversa)
    assert "outro jeito" in falar(conversa, s, "xyzzy blorft")["texto"]


def test_texto_sem_sentido_nao_apaga_atendimento_anterior(conversa):
    s = sessao_com_email(conversa)
    falar(conversa, s, "a vpn não conecta de casa")
    falar(conversa, s, "xyzzy blorft")
    assert "Que bom" in falar(conversa, s, "resolveu")["texto"]


def test_numero_sem_outras_sugestoes(conversa):
    s = sessao_com_email(conversa)
    falar(conversa, s, "papel enroscado na impressora")
    s.outros_artigos = []
    assert "não tenho outras sugestões" in falar(conversa, s, "2")["texto"]


def test_ignora_bom_e_caracteres_invisiveis(conversa):
    s = conversa.sessao(None)
    assert "Em que posso ajudar" in falar(conversa, s, "﻿bom dia")["texto"]


def test_outro_problema_reinicia(conversa):
    s = sessao_com_email(conversa)
    falar(conversa, s, "a vpn não conecta")
    falar(conversa, s, "outro problema")
    assert s.ultimo is None


def test_resposta_estruturada_para_a_pagina(conversa):
    s = conversa.sessao(None)
    d = falar(conversa, s, "xxxxx3@empresa.com", "minha conta está bloqueada, não consigo entrar")["detalhes"]
    assert d["tipo"] == "atendimento" and d["protocolo"].startswith("CH-")
    assert d["passos"]["titulo"] and len(d["passos"]["itens"]) >= 3
    assert any("desbloqueada com sucesso" in linha for linha in d["conta"])
    assert falar(conversa, conversa.sessao(None), "minha senha expirou")["detalhes"] == {"tipo": "pedir_email"}


def ler_avaliacoes(cfg):
    with cfg.avaliacoes.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def test_resolveu_pede_avaliacao_e_registra_uma_vez(conversa, cfg):
    s = sessao_com_email(conversa)
    falar(conversa, s, "a vpn não conecta de casa")
    protocolo = s.protocolo
    d = falar(conversa, s, "resolveu")["detalhes"]
    assert d["tipo"] == "resolvido" and d["protocolo"] == protocolo
    r = conversa.avaliar(s, 4, "  rápido   e claro ", protocolo)
    assert r["detalhes"] == {"tipo": "avaliado", "nota": 4, "rotulo": "Bom"}
    [linha] = ler_avaliacoes(cfg)
    assert linha["protocolo"] == protocolo and linha["nota"] == "4" and linha["comentario"] == "rápido e claro"
    assert linha["categoria"] == "Rede/VPN" and linha["solucao"] and linha["descricao"] == "a vpn não conecta de casa"
    with pytest.raises(ValueError):
        conversa.avaliar(s, 5)


def test_nota_digitada_no_chat(conversa, cfg):
    s = sessao_com_email(conversa)
    falar(conversa, s, "a impressora não imprime", "funcionou")
    assert falar(conversa, s, "5")["detalhes"]["nota"] == 5
    assert ler_avaliacoes(cfg)[0]["nota"] == "5"


def test_sem_atendimento_resolvido_nao_avalia(conversa, cfg):
    s = sessao_com_email(conversa)
    with pytest.raises(ValueError):
        conversa.avaliar(s, 3)
    falar(conversa, s, "a vpn não conecta de casa", "não resolveu")
    with pytest.raises(ValueError):
        conversa.avaliar(s, 3)
    assert not cfg.avaliacoes.exists()


def test_avaliacao_pela_web(cfg):
    cliente = TestClient(criar_app(cfg))
    sessao, _ = chat_web(cliente, cfg, "a vpn não conecta de casa")
    protocolo = cliente.post("/chat", json={"sessao": sessao, "mensagem": "resolveu"}).json()["detalhes"]["protocolo"]
    assert cliente.post("/avaliacao", json={"sessao": sessao, "protocolo": protocolo, "nota": 6}).status_code == 422
    assert cliente.post("/avaliacao", json={"sessao": sessao, "protocolo": "CH-outro", "nota": 3}).status_code == 409
    r = cliente.post("/avaliacao", json={"sessao": sessao, "protocolo": protocolo, "nota": 2, "comentario": "demorou"})
    assert r.status_code == 200 and r.json()["detalhes"]["nota"] == 2
    assert cliente.post("/avaliacao", json={"sessao": sessao, "protocolo": protocolo, "nota": 2}).status_code == 409


def test_chat_web_sem_chave(cfg):
    cliente = TestClient(criar_app(cfg))
    assert "Suporte de TI" in cliente.get("/").text
    for arquivo in ("/arquivos/visual/base.css", "/arquivos/visual/fontes/ibm-plex-sans-latin-400-normal.woff2",
                    "/arquivos/chat/chat.css", "/arquivos/chat/chat.js",
                    "/arquivos/painel/painel.css", "/arquivos/painel/painel.js"):
        assert cliente.get(arquivo).status_code == 200, arquivo
    assert cliente.get("/arquivos/painel/../tecnicos.json").status_code == 404
    assert cliente.get("/arquivos/chat/../chat_terminal.py").status_code == 404
    assert cliente.post("/chat", json={"mensagem": ""}).status_code == 401
    entrar_no_chat(cliente, cfg, "xxxxx4@teste.com", "XXXXX")
    r = cliente.post("/chat", json={"mensagem": ""}).json()
    assert r["sessao"] and "Olá, XXXXX!" in r["texto"] and "xxxxx4@teste.com" in r["texto"]
    r2 = cliente.post("/chat", json={"sessao": r["sessao"], "mensagem": "a impressora não imprime"}).json()
    assert r2["sessao"] == r["sessao"] and r2["detalhes"]["categoria"] == "Impressora"
