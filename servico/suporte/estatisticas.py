import csv
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .seguranca import linha_original, linha_segura

CAMPOS = ["data", "evento", "protocolo", "email", "categoria", "urgencia", "solucao", "texto"]
EVENTOS = ("atendido", "resolvido", "encaminhado", "nao_entendido")
FORMATO = "%d/%m/%Y %H:%M"


def _data(texto: str) -> datetime | None:
    try:
        return datetime.strptime(texto, FORMATO)
    except (TypeError, ValueError):
        return None


def _ler_csv(arquivo: Path) -> list[dict]:
    if not arquivo.exists():
        return []
    try:
        with arquivo.open(encoding="utf-8-sig", newline="") as f:
            return [linha_original(l) for l in csv.DictReader(f, delimiter=";")]
    except PermissionError:
        return []


class Atendimentos:
    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        self._trava = threading.Lock()

    def registrar(self, evento: str, **campos) -> None:
        if evento not in EVENTOS:
            raise ValueError(evento)
        linha = {c: "" for c in CAMPOS} | {k: str(v or "") for k, v in campos.items() if k in CAMPOS} | {
            "data": f"{datetime.now():{FORMATO}}", "evento": evento}
        linha["texto"] = linha["texto"][:300]
        with self._trava:
            novo = not self.arquivo.exists()
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.arquivo.open("a", encoding="utf-8-sig" if novo else "utf-8", newline="") as f:
                    escritor = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";")
                    if novo:
                        escritor.writeheader()
                    escritor.writerow(linha_segura(linha))
            except PermissionError:
                pass

    def listar(self) -> list[dict]:
        with self._trava:
            return _ler_csv(self.arquivo)


def indicadores(eventos: list[dict], chamados: list[dict], avaliacoes: list[dict], nomes: dict[str, str],
                dias: int = 14, agora: datetime | None = None) -> dict:
    agora = agora or datetime.now()

    por_protocolo: dict[str, dict] = {}
    for e in eventos:
        if e["evento"] == "nao_entendido" or not e["protocolo"]:
            continue
        p = por_protocolo.setdefault(e["protocolo"], {"categoria": "", "solucao": "", "data": None, "desfecho": ""})
        if e["evento"] == "atendido":
            p.update(categoria=e["categoria"], solucao=e["solucao"], data=_data(e["data"]))
        elif e["evento"] in ("resolvido", "encaminhado") and not p["desfecho"]:
            p["desfecho"] = e["evento"]
            p["categoria"] = p["categoria"] or e["categoria"]
            p["data"] = p["data"] or _data(e["data"])
    atendimentos = [p for p in por_protocolo.values() if p["data"]]
    resolvidos = sum(1 for p in atendimentos if p["desfecho"] == "resolvido")
    encaminhados = sum(1 for p in atendimentos if p["desfecho"] == "encaminhado")
    com_desfecho = resolvidos + encaminhados

    categorias: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "resolvidos": 0, "encaminhados": 0})
    for p in atendimentos:
        c = categorias[p["categoria"] or "Não classificado"]
        c["total"] += 1
        c["resolvidos"] += p["desfecho"] == "resolvido"
        c["encaminhados"] += p["desfecho"] == "encaminhado"

    hoje = agora.date()
    por_dia = Counter(p["data"].date() for p in atendimentos)
    atividade = [{"dia": (hoje - timedelta(days=i)).strftime("%d/%m"), "atendimentos": por_dia[hoje - timedelta(days=i)]}
                 for i in reversed(range(dias))]

    nao_entendidas = Counter(" ".join(e["texto"].split()).lower() for e in eventos
                             if e["evento"] == "nao_entendido" and e["texto"].strip())

    notas = [int(a["nota"]) for a in avaliacoes if str(a.get("nota", "")).isdigit()]
    por_solucao: dict[str, list[int]] = defaultdict(list)
    for a in avaliacoes:
        if str(a.get("nota", "")).isdigit() and a.get("solucao"):
            por_solucao[a["solucao"]].append(int(a["nota"]))
    medias = sorted(((round(sum(n) / len(n), 1), len(n), s) for s, n in por_solucao.items()), key=lambda x: (x[0], -x[1]))
    piores = [{"solucao": s, "media": media, "avaliacoes": qtd} for media, qtd, s in medias[:5]]

    def atrasado(c: dict) -> bool:
        limite = _data(c.get("previsao", ""))
        return c["status"] != "Concluído" and limite is not None and limite < agora

    duracoes = [(fim - ini).total_seconds() / 60 for c in chamados if c["status"] == "Concluído"
                if (ini := _data(c["data"])) and (fim := _data(c["atualizado_em"])) and fim >= ini]
    tecnicos: dict[str, dict] = {}
    for c in chamados:
        if not c.get("tecnico"):
            continue
        t = tecnicos.setdefault(c["tecnico"], {"nome": nomes.get(c["tecnico"], c["tecnico"]), "abertos": 0,
                                               "em_atendimento": 0, "concluidos": 0, "atrasados": 0})
        t["abertos"] += c["status"] == "Aberto"
        t["em_atendimento"] += c["status"] == "Em atendimento"
        t["concluidos"] += c["status"] == "Concluído"
        t["atrasados"] += atrasado(c)

    return {
        "chat": {
            "atendimentos": len(atendimentos), "resolvidos": resolvidos, "encaminhados": encaminhados,
            "sem_desfecho": len(atendimentos) - com_desfecho,
            "taxa_resolucao": round(100 * resolvidos / com_desfecho) if com_desfecho else None,
        },
        "atividade": atividade,
        "categorias": [{"categoria": k} | v for k, v in sorted(categorias.items(), key=lambda kv: -kv[1]["total"])],
        "nao_entendidas": [{"texto": t, "vezes": n} for t, n in nao_entendidas.most_common(10)],
        "avaliacoes": {
            "total": len(notas), "media": round(sum(notas) / len(notas), 1) if notas else None,
            "distribuicao": [{"nota": n, "quantidade": notas.count(n)} for n in range(1, 6)],
            "piores_solucoes": piores,
        },
        "fila": {
            "abertos": sum(c["status"] == "Aberto" for c in chamados),
            "em_atendimento": sum(c["status"] == "Em atendimento" for c in chamados),
            "concluidos": sum(c["status"] == "Concluído" for c in chamados),
            "atrasados": sum(atrasado(c) for c in chamados),
            "sem_responsavel": sum(c["status"] != "Concluído" and c.get("tecnico", "") not in nomes for c in chamados),
            "tempo_medio_minutos": round(sum(duracoes) / len(duracoes)) if duracoes else None,
        },
        "tecnicos": sorted(tecnicos.values(), key=lambda x: x["nome"]),
    }


def ler_avaliacoes(arquivo: Path) -> list[dict]:
    return _ler_csv(arquivo)
