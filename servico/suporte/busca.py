import difflib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .texto import Analisador, normalizar, tokens

K1 = 1.2
B = 0.75
BONUS_BIGRAMA = 0.5
CORTE_SIMILAR = 0.85
MIN_LETRAS_CORRECAO = 5


@dataclass
class Documento:
    id: str
    campos: dict[str, str]
    dados: dict = field(default_factory=dict)


@dataclass
class Resultado:
    documento: Documento
    score: float
    termos_encontrados: list[str]


@dataclass
class Consulta:
    termos: list[str]
    palavras: dict[str, str]
    correcoes: dict[str, str]


class IndiceBM25:
    def __init__(self, documentos: list[Documento], pesos: dict[str, float], analisador: Analisador):
        self.documentos = documentos
        self.pesos = pesos
        self.analisador = analisador

        self._tf: list[dict[str, float]] = []
        self._bigramas: list[set[tuple[str, str]]] = []
        self._tamanho: list[float] = []
        self._superficie: dict[str, str] = {}
        df: Counter[str] = Counter()
        for doc in documentos:
            tf: dict[str, float] = defaultdict(float)
            bigramas: set[tuple[str, str]] = set()
            for campo, peso in pesos.items():
                palavras = tokens(doc.campos.get(campo, ""))
                termos = [analisador.termo(p) for p in palavras]
                for p, t in zip(palavras, termos):
                    self._superficie.setdefault(normalizar(p), t)
                for t in termos:
                    tf[t] += peso
                bigramas.update(zip(termos, termos[1:]))
            self._tf.append(tf)
            self._bigramas.append(bigramas)
            self._tamanho.append(sum(tf.values()))
            df.update(tf.keys())

        n = len(documentos)
        self._media = (sum(self._tamanho) / n) if n else 1.0
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._palavras_conhecidas = sorted(p for p in self._superficie if len(p) >= MIN_LETRAS_CORRECAO)

    def analisar_consulta(self, consulta: str) -> Consulta:
        termos, palavras, correcoes = [], {}, {}
        for palavra in tokens(consulta):
            termo = self.analisador.termo(palavra)
            if termo not in self._idf:
                p = normalizar(palavra)
                if len(p) < MIN_LETRAS_CORRECAO:
                    continue
                parecida = difflib.get_close_matches(p, self._palavras_conhecidas, n=1, cutoff=CORTE_SIMILAR)
                if not parecida:
                    continue
                correcoes[palavra] = parecida[0]
                termo = self._superficie[parecida[0]]
            termos.append(termo)
            palavras.setdefault(termo, palavra)
        return Consulta(termos, palavras, correcoes)

    def buscar(self, consulta: str | Consulta, limite: int = 10, excluir=None) -> list[Resultado]:
        c = consulta if isinstance(consulta, Consulta) else self.analisar_consulta(consulta)
        termos = c.termos
        unicos = list(dict.fromkeys(termos))
        pares = set(zip(termos, termos[1:]))
        resultados = []
        for i, doc in enumerate(self.documentos):
            if excluir and excluir(doc):
                continue
            tf, tamanho = self._tf[i], self._tamanho[i]
            score, achados = 0.0, []
            for t in unicos:
                f = tf.get(t, 0)
                if not f:
                    continue
                achados.append(c.palavras[t])
                score += self._idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * tamanho / self._media))
            if score:
                score += BONUS_BIGRAMA * len(pares & self._bigramas[i])
                resultados.append(Resultado(doc, round(score, 3), achados))
        resultados.sort(key=lambda r: r.score, reverse=True)
        return resultados[:limite]
