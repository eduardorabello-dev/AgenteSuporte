import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import snowballstemmer

STOPWORDS = frozenset("""
    a o as os um uma uns umas de da do das dos em na no nas nos para pra por pelo pela com sem que se
    e ou mas ja nao sim muito muita mais menos meu minha meus minhas seu sua eu ele ela nos voces
    esta estou esta estao foi ser ter tem tenho fica ficou todo toda todos todas isso esse essa este
    quando ainda desde hoje ontem agora vez vezes dia preciso consigo aparece favor ajuda problema
    qualquer alguma algum coisa ao aos la aqui ate depois antes sobre entre como qual onde porque
    quero queria gostaria bom boa tarde noite ola oi obrigado obrigada att atenciosamente pessoal
""".split())

_STEMMER = snowballstemmer.stemmer("portuguese")

_EXPRESSOES = {"e-mail": "email", "wi-fi": "wifi", "home office": "homeoffice", "de casa": "decasa",
               "dois fatores": "doisfatores", "tomada de rede": "tomadaderede"}


def normalizar(texto: object) -> str:
    sem_acento = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn").strip()


def _juntar_expressoes(texto: str) -> str:
    for de, para in _EXPRESSOES.items():
        texto = texto.replace(de, para)
    return texto


@lru_cache(maxsize=50_000)
def radical(palavra: str) -> str:
    return normalizar(_STEMMER.stemWord(palavra))


def tokens(texto: object) -> list[str]:
    minusculo = _juntar_expressoes(str(texto or "").lower())
    return [t for t in re.split(r"[^\wà-ÿ]+", minusculo) if len(t) > 1 and normalizar(t) not in STOPWORDS]


class Analisador:

    def __init__(self, caminho_sinonimos: Path | None = None):
        self._canonico: dict[str, str] = {}
        if caminho_sinonimos and caminho_sinonimos.exists():
            grupos = json.loads(caminho_sinonimos.read_text(encoding="utf-8"))["grupos"]
            for grupo in grupos:
                principal = self._radical_expr(grupo[0])
                for palavra in grupo:
                    self._canonico[self._radical_expr(palavra)] = principal

    @staticmethod
    def _radical_expr(expressao: str) -> str:
        partes = tokens(expressao) or [expressao.lower()]
        return radical(partes[0]) if len(partes) == 1 else radical("".join(partes))

    def termo(self, palavra: str) -> str:
        r = radical(palavra)
        if r in self._canonico:
            return self._canonico[r]
        if r.endswith("s") and r[:-1] in self._canonico:
            return self._canonico[r[:-1]]
        return r

    def termos(self, texto: object) -> list[str]:
        return [self.termo(t) for t in tokens(texto)]
