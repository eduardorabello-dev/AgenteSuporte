from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from .texto import normalizar

COLUNAS = {
    "id": ("id",),
    "descricao": ("descricao",),
    "categoria": ("categoria esperada", "categoria"),
    "urgencia": ("urgencia esperada", "urgencia"),
}


@dataclass(frozen=True)
class ChamadoRotulado:
    id: str
    descricao: str
    categoria: str
    urgencia: str


def _celula(valor: object) -> str:
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    texto = str(valor if valor is not None else "").strip()
    return texto[:-2] if texto.endswith(".0") and texto[:-2].isdigit() else texto


class Planilha:

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self._mtime: float | None = None
        self._linhas: list[ChamadoRotulado] = []

    def linhas(self) -> list[ChamadoRotulado]:
        mtime = self.caminho.stat().st_mtime
        if mtime != self._mtime:
            self._linhas = self._ler()
            self._mtime = mtime
        return self._linhas

    def _ler(self) -> list[ChamadoRotulado]:
        livro = load_workbook(self.caminho, read_only=True, data_only=True)
        try:
            linhas = list(livro.worksheets[0].iter_rows(values_only=True))
        finally:
            livro.close()
        if not linhas:
            raise ValueError(f"A planilha {self.caminho} está vazia.")

        cabecalho = [normalizar(c) for c in linhas[0]]
        indice = {}
        for campo, nomes in COLUNAS.items():
            achado = next((i for i, c in enumerate(cabecalho) if c in nomes), None)
            if achado is None:
                raise ValueError(f"Coluna '{campo}' não encontrada na planilha. Cabeçalho lido: {linhas[0]}")
            indice[campo] = achado

        resultado = []
        for linha in linhas[1:]:
            valores = {campo: _celula(linha[i] if i < len(linha) else None) for campo, i in indice.items()}
            if valores["descricao"] and valores["categoria"]:
                resultado.append(ChamadoRotulado(**valores))
        if not resultado:
            raise ValueError(f"A planilha {self.caminho} não tem linhas com descrição e categoria.")
        return resultado
