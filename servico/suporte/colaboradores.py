import csv
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from .seguranca import linha_original, linha_segura

log = logging.getLogger("suporte")

CAMPOS = ["email", "nome", "primeiro_contato", "ultimo_contato", "atendimentos", "chamados_encaminhados",
          "ultimo_protocolo"]


def _agora() -> str:
    return f"{datetime.now():%d/%m/%Y %H:%M}"


class Colaboradores:
    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        self._trava = threading.Lock()

    def _ler(self) -> list[dict]:
        if not self.arquivo.exists():
            return []
        with self.arquivo.open(encoding="utf-8-sig", newline="") as f:
            return [{c: (l.get(c) or "") for c in CAMPOS} for l in map(linha_original, csv.DictReader(f, delimiter=";"))]

    def _gravar(self, linhas: list[dict]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo.with_suffix(".tmp")
        with temporario.open("w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";")
            escritor.writeheader()
            escritor.writerows(linha_segura(l) for l in sorted(linhas, key=lambda l: l["email"]))
        os.replace(temporario, self.arquivo)

    def _atualizar(self, email: str, mudar) -> None:
        email = email.strip().lower()
        if not email:
            return
        with self._trava:
            try:
                linhas = self._ler()
                linha = next((l for l in linhas if l["email"] == email), None)
                if linha is None:
                    linha = {c: "" for c in CAMPOS} | {"email": email, "primeiro_contato": _agora(),
                                                       "atendimentos": "0", "chamados_encaminhados": "0"}
                    linhas.append(linha)
                mudar(linha)
                linha["ultimo_contato"] = _agora()
                self._gravar(linhas)
            except PermissionError:
                log.warning("colaboradores.csv aberto no Excel: o contato de %s não foi atualizado agora", email)

    def registrar_contato(self, email: str, nome: str = "") -> None:
        def mudar(l: dict) -> None:
            l["atendimentos"] = str(int(l["atendimentos"] or 0) + 1)
            if nome:
                l["nome"] = nome
        self._atualizar(email, mudar)

    def registrar_chamado(self, email: str, protocolo: str) -> None:
        def mudar(l: dict) -> None:
            l["chamados_encaminhados"] = str(int(l["chamados_encaminhados"] or 0) + 1)
            l["ultimo_protocolo"] = protocolo
        self._atualizar(email, mudar)

    def listar(self) -> list[dict]:
        with self._trava:
            return self._ler()
