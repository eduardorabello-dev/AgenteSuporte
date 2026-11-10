from pathlib import Path

import pytest
from openpyxl import Workbook

from suporte.config import CONHECIMENTO, Config

LINHAS = [
    ("ID", "Descricao", "categoria esperada", "Urgencia Esperada"),
    (1.0, "Minha senha do Windows expirou e não consigo entrar no computador.", "Senha/Acesso", "Alta"),
    (2.0, "Conta bloqueada após três tentativas erradas de login.", "Senha/Acesso", "Alta"),
    (3.0, "Não consigo conectar na VPN para trabalhar de casa.", "Rede/VPN", "Alta"),
    (4.0, "A internet do meu setor caiu e ninguém consegue acessar o sistema.", "Rede/VPN", "Crítica"),
    (5.0, "Acabou o toner da impressora da recepção.", "Impressora", "Baixa"),
    (6.0, "A impressora do financeiro não imprime, fica na fila.", "Impressora", "Média"),
    (7.0, "O mouse do meu computador parou de funcionar.", "Hardware", "Baixa"),
]


EMAIL_TESTE = "colaborador@empresa.com"


def sessao_com_email(conversa, email: str = EMAIL_TESTE):
    s = conversa.sessao(None)
    conversa.responder(s, email)
    return s


SENHA_COLABORADOR = "Chamado2026x"


def entrar_no_chat(cliente, cfg, email: str = EMAIL_TESTE, nome: str = "Colaborador Teste") -> None:
    from suporte.contas import Contas
    contas = Contas(cfg.contas_colaboradores)
    try:
        provisoria = contas.adicionar(email, nome, "colaborador")
    except ValueError:
        provisoria = contas.redefinir(email)
    assert cliente.post("/chat/entrar", json={"email": email, "senha": provisoria}).status_code == 200
    assert cliente.post("/chat/senha", json={"atual": provisoria, "nova": SENHA_COLABORADOR}).status_code == 200


def chat_web(cliente, cfg, problema: str, email: str = EMAIL_TESTE) -> tuple[str, dict]:
    if cliente.get("/chat/eu").status_code != 200:
        entrar_no_chat(cliente, cfg, email)
    sessao = cliente.post("/chat", json={"mensagem": ""}).json()["sessao"]
    r = cliente.post("/chat", json={"sessao": sessao, "mensagem": problema}).json()
    return sessao, r


@pytest.fixture
def planilha(tmp_path: Path) -> Path:
    livro = Workbook()
    for linha in LINHAS:
        livro.worksheets[0].append(linha)
    caminho = tmp_path / "chamados.xlsx"
    livro.save(caminho)
    return caminho


@pytest.fixture
def cfg(planilha: Path) -> Config:
    return Config(
        planilha=planilha, base_conhecimento=CONHECIMENTO / "base-conhecimento.json",
        sinonimos=CONHECIMENTO / "sinonimos.json", regras=CONHECIMENTO / "regras.json",
        usuarios_mock=Path(__file__).parent / "usuarios-teste.json",
        encaminhados=planilha.parent / "encaminhados.csv", diretorio_modo="mock", politica_expiracao_dias=90,
        ad_servidor="", ad_usuario="", ad_senha="", ad_base_dn="", ad_ssl=True,
        avaliacoes=planilha.parent / "avaliacoes.csv", tecnicos=planilha.parent / "tecnicos.json",
        mensagens=planilha.parent / "mensagens.csv", colaboradores=planilha.parent / "colaboradores.csv",
        contas_colaboradores=planilha.parent / "contas-colaboradores.json",
        atendimentos=planilha.parent / "atendimentos.csv",
    )
