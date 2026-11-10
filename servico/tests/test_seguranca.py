import csv
import time

from fastapi.testclient import TestClient

from suporte import contas as modulo_contas
from suporte.contas import ContasTecnicos
from suporte.main import criar_app
from suporte.registro import RegistroChamados
from suporte.seguranca import celula_original, celula_segura
from tests.conftest import chat_web, entrar_no_chat


def test_pagina_inicial_leva_ao_chat_e_ao_painel(cfg):
    cliente = TestClient(criar_app(cfg))
    inicio = cliente.get("/").text
    assert 'href="/chat"' in inicio and 'href="/tecnico"' in inicio
    assert "Sou colaborador" in inicio and "Sou técnico de suporte" in inicio
    chat, painel = cliente.get("/chat").text, cliente.get("/tecnico").text
    assert 'id="mensagens"' in chat and 'id="painel-meus"' in chat
    for pagina in (chat, painel):
        assert 'id="acesso"' in pagina
        for js in ("preferencias.js", "idiomas.js", "acesso.js", "conta.js"):
            assert f"/arquivos/visual/{js}" in pagina
    for arquivo in ("/arquivos/inicio/inicio.css", "/arquivos/inicio/inicio.js", "/arquivos/visual/componentes.css",
                    "/arquivos/visual/idiomas.js", "/arquivos/visual/acesso.js", "/arquivos/visual/conta.js",
                    "/arquivos/visual/preferencias.js"):
        assert cliente.get(arquivo).status_code == 200, arquivo
    assert cliente.get("/arquivos/chat/../contas-colaboradores.json").status_code == 404


def test_cabecalhos_de_seguranca(cfg):
    cliente = TestClient(criar_app(cfg))
    for caminho in ("/", "/chat", "/tecnico", "/arquivos/visual/base.css", "/health"):
        h = cliente.get(caminho).headers
        assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h[
            "content-security-policy"], caminho
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
    assert cliente.get("/health").headers["cache-control"] == "no-store"
    assert cliente.get("/docs").status_code == 404 and cliente.get("/openapi.json").status_code == 404


def test_recusa_host_estranho_dns_rebinding(cfg):
    cliente = TestClient(criar_app(cfg))
    assert cliente.get("/health", headers={"host": "site-malicioso.com"}).status_code == 400
    assert cliente.get("/health", headers={"host": "127.0.0.1:5080"}).status_code == 200


def test_recusa_pedido_vindo_de_outro_site(cfg):
    cliente = TestClient(criar_app(cfg))
    entrar_no_chat(cliente, cfg)
    corpo = {"mensagem": "a vpn não conecta"}
    assert cliente.post("/chat", json=corpo, headers={"origin": "https://site-malicioso.com"}).status_code == 403
    assert cliente.post("/chat", json=corpo, headers={"origin": "null"}).status_code == 403
    assert cliente.post("/chat", json=corpo, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert cliente.post("/chat", json=corpo, headers={"origin": "http://testserver"}).status_code == 200


def test_cliente_nao_escolhe_o_id_da_sessao(cfg):
    cliente = TestClient(criar_app(cfg))
    entrar_no_chat(cliente, cfg)
    r = cliente.post("/chat", json={"sessao": "id-escolhido-por-mim", "mensagem": ""}).json()
    assert r["sessao"] != "id-escolhido-por-mim" and len(r["sessao"]) >= 30
    assert cliente.post("/chat", json={"sessao": "x" * 65, "mensagem": ""}).status_code == 422
    assert cliente.post("/chat", json={"mensagem": "a" * 2001}).status_code == 422


def test_chat_exige_login_e_cada_um_ve_so_o_seu(cfg):
    anonimo = TestClient(criar_app(cfg))
    for metodo, caminho, corpo in (("post", "/chat", {"mensagem": ""}), ("get", "/chat/meus-chamados", None),
                                   ("post", "/avaliacao", {"sessao": "x", "nota": 3})):
        r = anonimo.post(caminho, json=corpo) if metodo == "post" else anonimo.get(caminho)
        assert r.status_code == 401, caminho

    app = criar_app(cfg)
    xxxxx1, xxxxx2 = TestClient(app), TestClient(app)
    sessao_xxxxx1, _ = chat_web(xxxxx1, cfg, "a vpn não conecta de casa", "xxxxx1@teste.com")
    xxxxx1.post("/chat", json={"sessao": sessao_xxxxx1, "mensagem": "não resolveu"})
    entrar_no_chat(xxxxx2, cfg, "xxxxx2@teste.com", "XXXXX")

    assert xxxxx2.get("/chat/mensagens", params={"sessao": sessao_xxxxx1}).json()["mensagens"] == []
    assert xxxxx2.post("/chat/passos", json={"sessao": sessao_xxxxx1, "titulo": "x", "feitos": [0]}).status_code == 404
    r = xxxxx2.post("/chat", json={"sessao": sessao_xxxxx1, "mensagem": ""}).json()
    assert r["sessao"] != sessao_xxxxx1 and "xxxxx2@teste.com" in r["texto"]
    assert len(xxxxx1.get("/chat/meus-chamados").json()["chamados"]) == 1
    assert xxxxx2.get("/chat/meus-chamados").json()["chamados"] == []
    xxxxx1.post("/chat", json={"sessao": sessao_xxxxx1, "mensagem": "sou xxxxx2@teste.com"})
    assert len(xxxxx2.get("/chat/meus-chamados").json()["chamados"]) == 0


def test_csv_sem_formulas_do_excel(tmp_path):
    for perigoso in ("=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SOMA(A1)"):
        assert celula_segura(perigoso).startswith("'")
        assert celula_original(celula_segura(perigoso)) == perigoso
    assert celula_segura("texto normal") == "texto normal"

    registro = RegistroChamados(tmp_path / "c.csv", {"Média": 120}, 10)
    registro.registrar({"protocolo": "CH-1", "urgencia": "Média", "descricao": "=cmd|' /C calc'!A0"})
    with (tmp_path / "c.csv").open(encoding="utf-8-sig") as f:
        assert next(csv.DictReader(f, delimiter=";"))["descricao"].startswith("'=")
    assert registro.listar()[0]["descricao"] == "=cmd|' /C calc'!A0"


def test_sessao_do_tecnico_cai_por_inatividade(cfg, monkeypatch):
    contas = ContasTecnicos(cfg.tecnicos)
    senha = contas.adicionar("xxxxx8@teste.com", "XXXXX")
    s = contas.entrar("xxxxx8@teste.com", senha)
    assert contas.sessao(s.token) is not None
    agora = time.time()
    monkeypatch.setattr(modulo_contas.time, "time", lambda: agora + modulo_contas.INATIVIDADE_SEGUNDOS - 60)
    assert contas.sessao(s.token, renovar=False) is not None
    monkeypatch.setattr(modulo_contas.time, "time", lambda: agora + modulo_contas.INATIVIDADE_SEGUNDOS + 5)
    assert contas.sessao(s.token, renovar=False) is None
