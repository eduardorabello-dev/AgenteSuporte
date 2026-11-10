import json
from pathlib import Path

from .busca import Documento, IndiceBM25
from .texto import Analisador

MAX_ARTIGOS = 3
CORTE_RELATIVO = 0.4
RELEVANCIA_MINIMA = 3.0
PESOS = {"titulo": 3.0, "tags": 2.0, "solucao": 1.0}


class BaseConhecimento:
    def __init__(self, caminho: Path, analisador: Analisador):
        self.artigos = json.loads(caminho.read_text(encoding="utf-8"))
        documentos = [
            Documento(a["id"], {"titulo": a["titulo"], "tags": " ".join(a["tags"]), "solucao": " ".join(a["solucao"])}, a)
            for a in self.artigos
        ]
        self.indice = IndiceBM25(documentos, PESOS, analisador)

    def buscar(self, consulta: str, categoria: str | None = None) -> dict:
        analise = self.indice.analisar_consulta(consulta)
        resultados = self.indice.buscar(analise, limite=len(self.artigos))
        if categoria:
            for r in resultados:
                if r.documento.dados["categoria"] == categoria:
                    r.score = round(r.score * 1.2, 3)
            resultados.sort(key=lambda r: r.score, reverse=True)

        melhor = resultados[0].score if resultados else 0
        artigos = [
            {"id": a["id"], "titulo": a["titulo"], "categoria": a["categoria"], "relevancia": r.score,
             "termos_encontrados": r.termos_encontrados, "passos": a["solucao"]}
            for r in resultados
            if r.score >= max(melhor * CORTE_RELATIVO, RELEVANCIA_MINIMA)
            for a in [r.documento.dados]
        ][:MAX_ARTIGOS]
        return {"consulta": consulta, "correcoes": analise.correcoes, "artigos": artigos}
