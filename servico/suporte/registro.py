import csv
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .seguranca import linha_original, linha_segura

CAMPOS = ["data", "protocolo", "email", "descricao", "categoria", "urgencia", "motivo", "acoes_executadas",
          "previsao", "status", "tecnico", "observacao", "atualizado_em", "atualizado_por",
          "historico_chat",
          "sessao"]
STATUS = ("Aberto", "Em atendimento", "Concluído")
ORDEM_URGENCIA = {"Crítica": 0, "Alta": 1, "Média": 2, "Baixa": 3}
FORMATO_DATA = "%d/%m/%Y %H:%M"


class ArquivoEmUso(Exception):
    pass


def _agora() -> str:
    return f"{datetime.now():{FORMATO_DATA}}"


def descrever_minutos(minutos: int) -> str:
    h, m = divmod(max(int(minutos), 0), 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


class RegistroChamados:
    def __init__(self, arquivo: Path, minutos_por_urgencia: dict[str, int], minutos_por_chamado_na_frente: int):
        self.arquivo = arquivo
        self.minutos_por_urgencia = minutos_por_urgencia
        self.minutos_por_chamado = minutos_por_chamado_na_frente
        self._trava = threading.RLock()


    def _ler(self) -> list[dict]:
        if not self.arquivo.exists():
            return []
        try:
            with self.arquivo.open(encoding="utf-8-sig", newline="") as f:
                linhas = [linha_original(l) for l in csv.DictReader(f, delimiter=";")]
        except PermissionError as e:
            raise ArquivoEmUso(f"feche o arquivo {self.arquivo.name} no Excel e tente de novo") from e
        resultado = []
        for bruta in linhas:
            l = {c: (bruta.get(c) or "") for c in CAMPOS}
            l["status"] = l["status"] or "Aberto"
            if not l["previsao"]:
                try:
                    aberto = datetime.strptime(l["data"], FORMATO_DATA)
                    base = self.minutos_por_urgencia.get(l["urgencia"], self.minutos_por_urgencia.get("Média", 120))
                    l["previsao"] = f"{aberto + timedelta(minutes=base):{FORMATO_DATA}}"
                except ValueError:
                    pass
            resultado.append(l)
        return resultado

    def _gravar(self, linhas: list[dict]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo.with_suffix(".tmp")
        with temporario.open("w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";")
            escritor.writeheader()
            escritor.writerows(linha_segura(l) for l in linhas)
        try:
            os.replace(temporario, self.arquivo)
        except PermissionError as e:
            temporario.unlink(missing_ok=True)
            raise ArquivoEmUso(f"feche o arquivo {self.arquivo.name} no Excel e tente de novo") from e


    def listar(self) -> list[dict]:
        with self._trava:
            return self._ler()

    def estimar(self, urgencia: str, linhas: list[dict] | None = None, tecnico: str | None = None) -> dict:
        with self._trava:
            linhas = self._ler() if linhas is None else linhas
        nivel = ORDEM_URGENCIA.get(urgencia, ORDEM_URGENCIA["Média"])
        na_frente = sum(1 for l in linhas if l["status"] != "Concluído"
                        and (tecnico is None or l["tecnico"] == tecnico)
                        and ORDEM_URGENCIA.get(l["urgencia"], ORDEM_URGENCIA["Média"]) <= nivel)
        base = self.minutos_por_urgencia.get(urgencia, self.minutos_por_urgencia.get("Média", 120))
        minutos = base + na_frente * self.minutos_por_chamado
        ate = datetime.now() + timedelta(minutes=minutos)
        return {"minutos": minutos, "texto": descrever_minutos(minutos), "ate": f"{ate:%H:%M}",
                "ate_data": f"{ate:{FORMATO_DATA}}", "na_frente": na_frente, "tecnico": tecnico or ""}

    @staticmethod
    def _menos_ocupado(linhas: list[dict], equipe: list[str]) -> str:
        if not equipe:
            return ""
        carga = {t: 0 for t in equipe}
        for l in linhas:
            if l["status"] != "Concluído" and l["tecnico"] in carga:
                carga[l["tecnico"]] += 1
        return min(equipe, key=lambda t: carga[t])

    def registrar(self, linha: dict, equipe: list[str] | None = None) -> dict:
        with self._trava:
            linhas = self._ler()
            tecnico = self._menos_ocupado(linhas, equipe or [])
            previsao = self.estimar(linha.get("urgencia", ""), linhas, tecnico or None)
            novo = {c: "" for c in CAMPOS} | linha | {
                "data": linha.get("data") or _agora(), "previsao": previsao["ate_data"], "status": "Aberto",
                "tecnico": tecnico, "atualizado_em": _agora(), "atualizado_por": "chat"}
            self._gravar([*linhas, novo])
            return previsao

    def distribuir(self, equipe: list[str], por: str = "") -> int:
        with self._trava:
            linhas = self._ler()
            livres = sorted((l for l in linhas if l["status"] != "Concluído" and l["tecnico"] not in equipe),
                            key=lambda l: (ORDEM_URGENCIA.get(l["urgencia"], 9), datetime_ou_min(l["data"])))
            for l in livres:
                l["tecnico"] = self._menos_ocupado(linhas, equipe)
                l["atualizado_em"], l["atualizado_por"] = _agora(), por
            if livres and equipe:
                self._gravar(linhas)
            return len(livres) if equipe else 0

    def atualizar_historico(self, protocolo: str, historico: str) -> None:
        with self._trava:
            linhas = self._ler()
            alvo = next((l for l in linhas if l["protocolo"] == protocolo), None)
            if alvo is not None and alvo["historico_chat"] != historico:
                alvo["historico_chat"] = historico
                self._gravar(linhas)

    def atualizar(self, protocolo: str, status: str | None = None, tecnico: str | None = None,
                  observacao: str | None = None, por: str = "") -> dict:
        if status is not None and status not in STATUS:
            raise ValueError(f"Status inválido: {status}")
        with self._trava:
            linhas = self._ler()
            alvo = next((l for l in linhas if l["protocolo"] == protocolo), None)
            if alvo is None:
                raise KeyError(protocolo)
            for campo, valor in (("status", status), ("tecnico", tecnico), ("observacao", observacao)):
                if valor is not None:
                    alvo[campo] = " ".join(valor.split())[:1000]
            alvo["atualizado_em"], alvo["atualizado_por"] = _agora(), por
            self._gravar(linhas)
            return alvo


def datetime_ou_min(texto: str) -> datetime:
    try:
        return datetime.strptime(texto, FORMATO_DATA)
    except ValueError:
        return datetime.min
