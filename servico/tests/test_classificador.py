import json
import os
from pathlib import Path

import pytest

from suporte.classificador import Classificador, Regras
from suporte.config import CONHECIMENTO
from suporte.planilha import Planilha
from suporte.texto import Analisador

PLANILHA_REAL = Path(os.environ.get("PLANILHA_CHAMADOS", r"E:\Downloads\chamados_teste.xlsx"))
ARTIGOS = json.loads((CONHECIMENTO / "base-conhecimento.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def analisador():
    return Analisador(CONHECIMENTO / "sinonimos.json")


@pytest.fixture(scope="module")
def regras():
    return Regras(CONHECIMENTO / "regras.json")


def test_le_planilha_e_normaliza_id(planilha):
    linhas = Planilha(planilha).linhas()
    assert len(linhas) == 7 and linhas[0].id == "1" and linhas[0].categoria == "Senha/Acesso"


def test_recarrega_quando_arquivo_muda(planilha):
    from openpyxl import load_workbook

    p = Planilha(planilha)
    assert len(p.linhas()) == 7
    livro = load_workbook(planilha)
    livro.worksheets[0].append((8.0, "Headset sem áudio.", "Telefonia/Headset", "Alta"))
    livro.save(planilha)
    os.utime(planilha, (planilha.stat().st_atime, planilha.stat().st_mtime + 5))
    assert len(p.linhas()) == 8


def test_coluna_ausente_da_erro_claro(tmp_path):
    from openpyxl import Workbook

    livro = Workbook()
    livro.worksheets[0].append(("ID", "Texto", "Categoria"))
    livro.save(tmp_path / "ruim.xlsx")
    with pytest.raises(ValueError, match="descricao"):
        Planilha(tmp_path / "ruim.xlsx").linhas()


def test_categorias_vem_da_planilha(planilha, analisador, regras):
    clf = Classificador(Planilha(planilha).linhas(), ARTIGOS, analisador, regras)
    assert clf.categorias == ["Senha/Acesso", "Rede/VPN", "Impressora", "Hardware"]
    r = clf.classificar("O toner da impressora do RH acabou")
    assert r["categoria"] == "Impressora"
    assert r["categoria"] in clf.categorias


def test_chamado_identico_nao_vota_em_si_mesmo(planilha, analisador, regras):
    clf = Classificador(Planilha(planilha).linhas(), ARTIGOS, analisador, regras)
    texto = "Acabou o toner da impressora da recepção."
    assert all(s["descricao"] != texto for s in clf.classificar(texto)["chamados_semelhantes"])


@pytest.mark.parametrize("texto, urgencia", [
    ("Todos do setor de vendas estão sem internet", "Crítica"),
    ("Recebi um email suspeito pedindo minha senha", "Alta"),
    ("Minha conta foi bloqueada e não consigo entrar", "Alta"),
    ("Como troco minha senha?", "Baixa"),
    ("O wi-fi está instável", "Média"),
])
def test_regras_de_urgencia(regras, texto, urgencia):
    assert regras.urgencia_por_regra(texto)[0] == urgencia


def test_seguranca(regras):
    assert regras.incidente_seguranca("Cliquei num link de um e-mail do banco")
    assert not regras.incidente_seguranca("A impressora não imprime")


@pytest.mark.skipif(not PLANILHA_REAL.exists(), reason="planilha real não disponível")
def test_acuracia_na_planilha_real(analisador, regras):
    base = Planilha(PLANILHA_REAL).linhas()
    clf = Classificador(base, ARTIGOS, analisador, regras)
    resultados = [clf.classificar(r.descricao) for r in base]
    acerto_cat = sum(res["categoria"] == r.categoria for res, r in zip(resultados, base)) / len(base)
    acerto_urg = sum(res["urgencia"] == r.urgencia for res, r in zip(resultados, base)) / len(base)
    assert acerto_cat >= 0.85, acerto_cat
    assert acerto_urg >= 0.85, acerto_urg
