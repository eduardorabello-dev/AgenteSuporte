import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ITERACOES = 310_000
TENTATIVAS_ANTES_DE_BLOQUEAR = 5
BLOQUEIO_SEGUNDOS = 5 * 60
DURACAO_SESSAO_SEGUNDOS = 8 * 60 * 60
INATIVIDADE_SEGUNDOS = 30 * 60
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


class SenhaFraca(ValueError):
    pass


class LoginBloqueado(Exception):
    def __init__(self, segundos: int):
        super().__init__(f"Muitas tentativas. Tente de novo em {max(1, round(segundos / 60))} min.")


def _hash(senha: str, sal: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, ITERACOES).hex()


def gerar_senha_provisoria() -> str:
    alfabeto = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    bloco = lambda: "".join(secrets.choice(alfabeto) for _ in range(4))
    return f"Prov-{bloco()}-{bloco()}"


def validar_nova_senha(nova: str, email: str) -> None:
    if len(nova) < 8:
        raise SenhaFraca("A senha precisa ter pelo menos 8 caracteres.")
    if not re.search(r"[A-Za-z]", nova) or not re.search(r"\d", nova):
        raise SenhaFraca("A senha precisa ter letras e números.")
    if nova.lower().startswith("prov-"):
        raise SenhaFraca("Escolha uma senha sua, diferente do formato da provisória.")
    usuario = email.split("@")[0].lower()
    if len(usuario) >= 4 and usuario in nova.lower():
        raise SenhaFraca("A senha não pode conter o seu e-mail.")


@dataclass
class Sessao:
    token: str
    email: str
    expira_em: float
    trocar_senha: bool
    hash_senha: str
    ultimo_uso: float = 0.0


class ContasTecnicos:
    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        self._trava = threading.RLock()
        self._sessoes: dict[str, Sessao] = {}
        self._falhas: dict[str, tuple[int, float]] = {}


    def _ler(self) -> list[dict]:
        if not self.arquivo.exists():
            return []
        return json.loads(self.arquivo.read_text(encoding="utf-8"))

    def _gravar(self, contas: list[dict]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(contas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporario, self.arquivo)

    def _conta(self, contas: list[dict], email: str) -> dict | None:
        email = email.strip().lower()
        return next((c for c in contas if c["email"] == email), None)

    @staticmethod
    def _definir_senha(conta: dict, senha: str, provisoria: bool) -> None:
        sal = secrets.token_bytes(16)
        conta.update({"sal": sal.hex(), "hash": _hash(senha, sal), "senha_provisoria": provisoria,
                      "senha_alterada_em": f"{datetime.now():%d/%m/%Y %H:%M}"})


    def equipe(self) -> list[dict]:
        with self._trava:
            return [{"email": c["email"], "nome": c["nome"], "papel": c.get("papel", "tecnico")}
                    for c in self._ler() if c.get("ativo", True)]

    def adicionar(self, email: str, nome: str, papel: str = "tecnico") -> str:
        email = email.strip().lower()
        if not EMAIL.match(email):
            raise ValueError(f"E-mail inválido: {email}")
        with self._trava:
            contas = self._ler()
            if self._conta(contas, email):
                raise ValueError(f"A conta {email} já existe. Use 'redefinir' para gerar outra senha provisória.")
            senha = gerar_senha_provisoria()
            conta = {"email": email, "nome": nome.strip(), "papel": papel, "ativo": True}
            self._definir_senha(conta, senha, provisoria=True)
            contas.append(conta)
            self._gravar(contas)
            return senha

    def listar_detalhes(self) -> list[dict]:
        with self._trava:
            return [{"email": c["email"], "nome": c["nome"], "papel": c.get("papel", "tecnico"),
                     "ativo": c.get("ativo", True), "senha_provisoria": bool(c.get("senha_provisoria")),
                     "senha_alterada_em": c.get("senha_alterada_em", ""), "ultimo_login": c.get("ultimo_login", "")}
                    for c in sorted(self._ler(), key=lambda c: c["nome"].lower())]

    def definir_ativo(self, email: str, ativo: bool) -> None:
        with self._trava:
            contas = self._ler()
            conta = self._conta(contas, email)
            if conta is None:
                raise KeyError(email)
            conta["ativo"] = bool(ativo)
            self._gravar(contas)
            if not ativo:
                self._encerrar_sessoes(conta["email"])

    def redefinir(self, email: str) -> str:
        with self._trava:
            contas = self._ler()
            conta = self._conta(contas, email)
            if conta is None:
                raise KeyError(email)
            senha = gerar_senha_provisoria()
            self._definir_senha(conta, senha, provisoria=True)
            self._gravar(contas)
            self._encerrar_sessoes(conta["email"])
            self._falhas.pop(conta["email"], None)
            return senha


    def entrar(self, email: str, senha: str) -> Sessao:
        email = email.strip().lower()
        with self._trava:
            tentativas, bloqueado_ate = self._falhas.get(email, (0, 0.0))
            if bloqueado_ate > time.time():
                raise LoginBloqueado(int(bloqueado_ate - time.time()))
            conta = self._conta(self._ler(), email)
            calculado = _hash(senha, bytes.fromhex(conta["sal"]) if conta else b"\0" * 16)
            confere = conta is not None and hmac.compare_digest(calculado, conta["hash"])
            if conta is None or not confere or not conta.get("ativo", True):
                tentativas += 1
                bloqueio = time.time() + BLOQUEIO_SEGUNDOS if tentativas >= TENTATIVAS_ANTES_DE_BLOQUEAR else 0.0
                self._falhas[email] = (0 if bloqueio else tentativas, bloqueio)
                raise PermissionError("E-mail ou senha incorretos.")
            self._falhas.pop(email, None)
            contas = self._ler()
            registro = self._conta(contas, email)
            if registro is not None:
                registro["login_anterior"] = registro.get("ultimo_login", "")
                registro["ultimo_login"] = f"{datetime.now():%d/%m/%Y %H:%M}"
                self._gravar(contas)
            sessao = Sessao(secrets.token_urlsafe(32), email, time.time() + DURACAO_SESSAO_SEGUNDOS,
                            bool(conta.get("senha_provisoria")), conta["hash"])
            self._sessoes[sessao.token] = sessao
            return sessao

    def sessao(self, token: str | None, renovar: bool = True) -> Sessao | None:
        with self._trava:
            s = self._sessoes.get(token or "")
            if s is None:
                return None
            conta = self._conta(self._ler(), s.email)
            agora = time.time()
            if (s.expira_em < agora or agora - (s.ultimo_uso or agora) > INATIVIDADE_SEGUNDOS or conta is None
                    or not conta.get("ativo", True) or conta["hash"] != s.hash_senha):
                self._sessoes.pop(s.token, None)
                return None
            if renovar or not s.ultimo_uso:
                s.ultimo_uso = agora
            return s

    def sair(self, token: str | None) -> None:
        with self._trava:
            self._sessoes.pop(token or "", None)

    def _encerrar_sessoes(self, email: str) -> None:
        for token in [t for t, s in self._sessoes.items() if s.email == email]:
            self._sessoes.pop(token, None)

    def trocar_senha(self, sessao: Sessao, atual: str, nova: str) -> None:
        with self._trava:
            contas = self._ler()
            conta = self._conta(contas, sessao.email)
            if conta is None:
                raise PermissionError("Conta não encontrada.")
            if not hmac.compare_digest(_hash(atual, bytes.fromhex(conta["sal"])), conta["hash"]):
                raise PermissionError("A senha atual não confere.")
            if nova == atual:
                raise SenhaFraca("A nova senha precisa ser diferente da atual.")
            validar_nova_senha(nova, sessao.email)
            self._definir_senha(conta, nova, provisoria=False)
            self._gravar(contas)
            self._encerrar_sessoes(sessao.email)
            sessao.trocar_senha, sessao.hash_senha = False, conta["hash"]
            self._sessoes[sessao.token] = sessao

    def nome(self, email: str) -> str:
        conta = next((c for c in self.equipe() if c["email"] == email), None)
        return conta["nome"] if conta else email

    def perfil(self, email: str) -> dict:
        with self._trava:
            conta = self._conta(self._ler(), email) or {}
        return {"email": email, "nome": conta.get("nome", email), "papel": conta.get("papel", ""),
                "senha_alterada_em": conta.get("senha_alterada_em", ""),
                "login_anterior": conta.get("login_anterior", "")}


Contas = ContasTecnicos
