import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .busca import Documento, IndiceBM25
from .planilha import ChamadoRotulado
from .texto import Analisador, normalizar

VIZINHOS = 7
PESO_ARTIGOS = 1.0
ALPHA_NB = 0.3
PESO_NB = 0.3
URGENCIA_PADRAO = "Média"


class NaiveBayes:

    def __init__(self, exemplos: list[tuple[str, set[str], str]], categorias: list[str]):
        self.exemplos = exemplos
        self.categorias = categorias
        self.contagem: dict[str, Counter] = defaultdict(Counter)
        self.total: Counter = Counter()
        for _, termos, cat in exemplos:
            self.contagem[cat].update(termos)
            self.total[cat] += len(termos)
        self.vocabulario = set().union(*self.contagem.values()) if self.contagem else set()

    def probabilidades(self, termos: set[str], excluir_chave: str | None = None) -> dict[str, float]:
        contagem, total = self.contagem, self.total
        if excluir_chave:
            for chave, t, cat in self.exemplos:
                if chave == excluir_chave:
                    contagem = {**contagem, cat: contagem[cat] - Counter(t)}
                    total = total.copy()
                    total[cat] -= len(t)
        conhecidos = [t for t in termos if t in self.vocabulario]
        v = len(self.vocabulario) or 1
        log = {c: sum(math.log((contagem[c][t] + ALPHA_NB) / (total[c] + ALPHA_NB * v)) for t in conhecidos)
               for c in self.categorias}
        maior = max(log.values())
        exp = {c: math.exp(s - maior) for c, s in log.items()}
        soma = sum(exp.values())
        return {c: e / soma for c, e in exp.items()}


@dataclass(frozen=True)
class RegraUrgencia:
    nivel: str
    motivo: str
    todas: tuple[re.Pattern, ...]
    alguma: tuple[re.Pattern, ...]
    usa_seguranca: bool


class Regras:

    def __init__(self, caminho: Path):
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        compilar = lambda lista: tuple(re.compile(p) for p in lista if p != "__seguranca__")
        self.seguranca = compilar(bruto["seguranca"])
        self.urgencia = [
            RegraUrgencia(r["nivel"], r["motivo"], compilar(r.get("todas", [])), compilar(r.get("alguma", [])),
                          "__seguranca__" in r.get("alguma", []))
            for r in bruto["urgencia"]
        ]
        self.gatilho_conta = compilar(bruto["acoes_conta"]["gatilho"])
        self.pedido_desbloqueio = compilar(bruto["acoes_conta"]["pedido_desbloqueio"])
        self.escalar_categorias = set(bruto["escalar_categorias"]["categorias"])
        self.motivo_escalar_categoria = bruto["escalar_categorias"]["motivo"]
        previsao = bruto.get("previsao_atendimento", {})
        self.minutos_por_urgencia: dict[str, int] = previsao.get(
            "minutos_por_urgencia", {"Crítica": 15, "Alta": 45, "Média": 120, "Baixa": 240})
        self.minutos_por_chamado_na_frente: int = previsao.get("minutos_por_chamado_na_frente", 10)

    @staticmethod
    def casa(padroes, texto: str) -> list[str]:
        return [m.group(0) for p in padroes if (m := p.search(texto))]

    def incidente_seguranca(self, texto: str) -> list[str]:
        return self.casa(self.seguranca, normalizar(texto))

    def urgencia_por_regra(self, texto: str) -> tuple[str, str, list[str]] | None:
        t = normalizar(texto)
        seguranca = bool(self.incidente_seguranca(t))
        for regra in self.urgencia:
            if regra.todas:
                trechos = self.casa(regra.todas, t)
                if len(trechos) == len(regra.todas):
                    return regra.nivel, regra.motivo, trechos
                continue
            trechos = self.casa(regra.alguma, t)
            if regra.usa_seguranca and seguranca:
                trechos.append("incidente de segurança")
            if trechos:
                return regra.nivel, regra.motivo, trechos
        return None


class Classificador:
    def __init__(self, base: list[ChamadoRotulado], artigos: list[dict], analisador: Analisador, regras: Regras):
        self.regras = regras
        self.categorias = list(dict.fromkeys(r.categoria for r in base))
        self.urgencias = list(dict.fromkeys(r.urgencia for r in base if r.urgencia))
        documentos = [Documento(f"planilha:{r.id}", {"texto": r.descricao}, {"chamado": r}) for r in base]
        documentos += [
            Documento(f"kb:{a['id']}", {"texto": f"{a['titulo']} {' '.join(a['tags'])}"}, {"artigo": a})
            for a in artigos
            if a["categoria"] in self.categorias
        ]
        self.indice = IndiceBM25(documentos, {"texto": 1.0}, analisador)
        self.analisador = analisador
        exemplos_nb = [(normalizar(r.descricao), set(analisador.termos(r.descricao)), r.categoria) for r in base]
        exemplos_nb += [(d.id, set(analisador.termos(d.campos["texto"])), d.dados["artigo"]["categoria"])
                        for d in documentos if "artigo" in d.dados]
        self.nb = NaiveBayes(exemplos_nb, self.categorias)

    def classificar(self, texto: str, descricao: str | None = None) -> dict:
        alvo = normalizar(descricao if descricao is not None else texto)
        mesmo = lambda d: "chamado" in d.dados and normalizar(d.dados["chamado"].descricao) == alvo
        vizinhos = self.indice.buscar(texto, limite=VIZINHOS, excluir=mesmo)

        votos_cat: dict[str, float] = defaultdict(float)
        semelhantes = []
        for v in vizinhos:
            if (c := v.documento.dados.get("chamado")) is not None:
                votos_cat[c.categoria] += v.score
                semelhantes.append({"id": c.id, "descricao": c.descricao, "categoria": c.categoria,
                                    "urgencia": c.urgencia, "similaridade": v.score})
            else:
                votos_cat[v.documento.dados["artigo"]["categoria"]] += v.score * PESO_ARTIGOS

        total = sum(votos_cat.values())
        termos = set(self.analisador.termos(texto))
        if total or termos & self.nb.vocabulario:
            p_nb = self.nb.probabilidades(termos, excluir_chave=alvo)
            p_votos = {c: votos_cat.get(c, 0.0) / total for c in self.categorias} if total else p_nb
            pontuacao = {c: PESO_NB * p_nb[c] + (1 - PESO_NB) * p_votos[c] for c in self.categorias}
            categoria = max(pontuacao, key=lambda c: pontuacao[c])
            confianca = round(pontuacao[categoria], 2)
        else:
            pontuacao = {}
            categoria, confianca = "Não classificado", 0.0

        votos_urg: dict[str, float] = defaultdict(float)
        for s in semelhantes:
            if s["categoria"] == categoria and s["urgencia"]:
                votos_urg[s["urgencia"]] += s["similaridade"]

        regra = self.regras.urgencia_por_regra(texto)
        if regra:
            urgencia, motivo, trechos = regra
            justificativa = f"Regra: {motivo} (trechos: {', '.join(trechos)})."
        elif votos_urg:
            urgencia = max(votos_urg, key=lambda u: votos_urg[u])
            justificativa = "Nenhuma regra de impacto casou; urgência dos chamados mais parecidos da planilha."
        else:
            urgencia, justificativa = URGENCIA_PADRAO, "Sem regra nem chamados parecidos; urgência padrão."

        return {
            "categoria": categoria,
            "confianca_categoria": confianca,
            "pontuacao_categorias": {c: round(s, 2) for c, s in sorted(pontuacao.items(), key=lambda x: -x[1]) if s >= 0.01},
            "urgencia": urgencia,
            "justificativa_urgencia": justificativa,
            "incidente_seguranca": bool(self.regras.incidente_seguranca(texto)),
            "chamados_semelhantes": semelhantes[:3],
        }
