import csv
import threading
import time
from datetime import datetime
from pathlib import Path

from .seguranca import linha_original, linha_segura

CAMPOS = ["id", "data", "protocolo", "autor", "nome", "texto"]
AUTORES = ("tecnico", "usuario", "sistema")
DIGITANDO_SEGUNDOS = 4
ONLINE_SEGUNDOS = 12
MAX_TEXTO = 2000


class Mensagens:
    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        self._trava = threading.RLock()
        self._historico: dict[str, list[dict]] | None = None
        self._ultimo_id: int = 0
        self._ativas: dict[str, dict] = {}
        self._digitando: dict[tuple[str, str], float] = {}
        self._visto: dict[str, float] = {}
        self._protocolos_da_sessao: dict[str, set[str]] = {}


    def _carregar(self) -> dict[str, list[dict]]:
        if self._historico is None:
            self._historico = {}
            if self.arquivo.exists():
                with self.arquivo.open(encoding="utf-8-sig", newline="") as f:
                    for linha in map(linha_original, csv.DictReader(f, delimiter=";")):
                        numero = int(linha.get("id") or 0)
                        m: dict = {c: linha.get(c) or "" for c in CAMPOS} | {"id": numero}
                        self._historico.setdefault(m["protocolo"], []).append(m)
                        self._ultimo_id = max(self._ultimo_id, numero)
        return self._historico

    def _gravar(self, m: dict) -> None:
        novo = not self.arquivo.exists()
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.arquivo.open("a", encoding="utf-8-sig" if novo else "utf-8", newline="") as f:
                escritor = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";")
                if novo:
                    escritor.writeheader()
                escritor.writerow(linha_segura(m))
        except PermissionError:
            pass

    def listar(self, protocolo: str, desde: int = 0) -> list[dict]:
        with self._trava:
            return [m for m in self._carregar().get(protocolo, []) if m["id"] > desde]

    def da_sessao(self, sessao: str, desde: int = 0) -> list[dict]:
        with self._trava:
            protocolos = self._protocolos_da_sessao.get(sessao, set())
            return sorted((m for p in protocolos for m in self.listar(p, desde)), key=lambda m: m["id"])

    def enviar(self, protocolo: str, autor: str, nome: str, texto: str) -> dict:
        if autor not in AUTORES:
            raise ValueError(f"Autor inválido: {autor}")
        texto = (texto or "").strip()[:MAX_TEXTO]
        if not texto:
            raise ValueError("A mensagem está vazia.")
        with self._trava:
            self._carregar()
            self._ultimo_id += 1
            m = {"id": self._ultimo_id, "data": f"{datetime.now():%d/%m/%Y %H:%M}", "protocolo": protocolo,
                 "autor": autor, "nome": nome, "texto": texto}
            assert self._historico is not None
            self._historico.setdefault(protocolo, []).append(m)
            self._gravar(m)
            self._digitando.pop((protocolo, autor), None)
            return m


    def iniciar(self, protocolo: str, sessao: str, tecnico: str, tecnico_nome: str) -> dict:
        with self._trava:
            ja_ativa = self._ativas.get(protocolo)
            self._ativas[protocolo] = {"sessao": sessao, "tecnico": tecnico, "tecnico_nome": tecnico_nome}
            self._protocolos_da_sessao.setdefault(sessao, set()).add(protocolo)
            if not ja_ativa or ja_ativa["tecnico"] != tecnico:
                self.enviar(protocolo, "sistema", tecnico_nome,
                            f"{tecnico_nome}, técnico de suporte, entrou na conversa sobre o chamado {protocolo}.")
            return self._ativas[protocolo]

    def encerrar(self, protocolo: str, por: str) -> None:
        with self._trava:
            if self._ativas.pop(protocolo, None):
                self.enviar(protocolo, "sistema", por, f"{por} encerrou a conversa. Se precisar, é só escrever "
                                                       "aqui que o assistente volta a te ajudar.")

    def ativa(self, protocolo: str) -> dict | None:
        with self._trava:
            return self._ativas.get(protocolo)

    def ativa_da_sessao(self, sessao: str) -> tuple[str, dict] | None:
        with self._trava:
            return next(((p, c) for p, c in self._ativas.items() if c["sessao"] == sessao), None)


    def avisar_digitando(self, protocolo: str, lado: str) -> None:
        with self._trava:
            self._digitando[(protocolo, lado)] = time.time()

    def digitando(self, protocolo: str, lado: str) -> bool:
        with self._trava:
            return time.time() - self._digitando.get((protocolo, lado), 0) < DIGITANDO_SEGUNDOS

    def marcar_visto(self, sessao: str) -> None:
        with self._trava:
            self._visto[sessao] = time.time()

    def online(self, sessao: str) -> bool:
        with self._trava:
            return bool(sessao) and time.time() - self._visto.get(sessao, 0) < ONLINE_SEGUNDOS
