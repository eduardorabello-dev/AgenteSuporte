import json
import math
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .config import Config


def _agora() -> datetime:
    return datetime.now().astimezone()


def _info_senha(login, nome, alterada_em, expira_em, nunca_expira=False, deve_trocar=False) -> dict:
    if nunca_expira:
        return {"login": login, "nome": nome, "senha_alterada_em": alterada_em, "senha_expira_em": None,
                "dias_restantes": None, "expirada": False, "nunca_expira": True, "deve_trocar_no_proximo_logon": False}
    expirada = deve_trocar or expira_em <= _agora()
    return {"login": login, "nome": nome, "senha_alterada_em": alterada_em, "senha_expira_em": expira_em,
            "dias_restantes": math.floor((expira_em - _agora()).total_seconds() / 86400),
            "expirada": expirada, "nunca_expira": False, "deve_trocar_no_proximo_logon": expirada}


def _status(login, nome, habilitada, bloqueada, bloqueada_desde, tentativas) -> dict:
    return {"login": login, "nome": nome, "habilitada": habilitada, "bloqueada": bloqueada,
            "bloqueada_desde": bloqueada_desde, "tentativas_invalidas": tentativas}


def _desbloqueio(login, desbloqueada, mensagem) -> dict:
    return {"login": login, "desbloqueada": desbloqueada, "mensagem": mensagem}


MSG_DESABILITADA = "Conta desabilitada: desbloqueio exige aprovação do gestor."
MSG_NAO_BLOQUEADA = "A conta não estava bloqueada. Nenhuma alteração feita."
MSG_DESBLOQUEADA = "Conta desbloqueada com sucesso."


class Diretorio(Protocol):

    def obter_senha(self, email: str) -> dict | None: ...
    def obter_status(self, email: str) -> dict | None: ...
    def desbloquear(self, email: str) -> dict | None: ...


class DiretorioMock:

    def __init__(self, caminho: Path, politica_padrao: int = 90):
        self._politica = politica_padrao
        self._lock = threading.Lock()
        self._usuarios = {u["email"].lower(): u for u in json.loads(caminho.read_text(encoding="utf-8"))}

    def _buscar(self, email: str) -> dict | None:
        return self._usuarios.get(email.strip().lower())

    def obter_senha(self, email):
        if not (u := self._buscar(email)):
            return None
        alterada = (_agora() - timedelta(days=u["senhaAlteradaHaDias"])).replace(hour=9, minute=0, second=0, microsecond=0)
        if u["nuncaExpira"]:
            return _info_senha(u["login"], u["nome"], alterada, None, nunca_expira=True)
        politica = u.get("politicaExpiracaoDias") or self._politica
        return _info_senha(u["login"], u["nome"], alterada, alterada + timedelta(days=politica))

    def obter_status(self, email):
        if not (u := self._buscar(email)):
            return None
        desde = _agora() - timedelta(minutes=12) if u["bloqueada"] else None
        return _status(u["login"], u["nome"], u["habilitada"], u["bloqueada"], desde, u["tentativasInvalidas"])

    def desbloquear(self, email):
        with self._lock:
            if not (u := self._buscar(email)):
                return None
            if not u["habilitada"]:
                return _desbloqueio(u["login"], False, MSG_DESABILITADA)
            if not u["bloqueada"]:
                return _desbloqueio(u["login"], False, MSG_NAO_BLOQUEADA)
            u["bloqueada"], u["tentativasInvalidas"] = False, 0
            return _desbloqueio(u["login"], True, MSG_DESBLOQUEADA)


UAC_DESABILITADA = 0x0002
UAC_BLOQUEADA = 0x0010
UAC_SENHA_NUNCA_EXPIRA = 0x10000
FILETIME_NUNCA = 0x7FFFFFFFFFFFFFFF


def _filetime(valor: int) -> datetime | None:
    if valor <= 0 or valor >= FILETIME_NUNCA:
        return None
    return (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=valor // 10)).astimezone()


class DiretorioActiveDirectory:

    def __init__(self, cfg: Config):
        from ldap3 import Server

        if not (cfg.ad_servidor and cfg.ad_usuario and cfg.ad_base_dn):
            raise RuntimeError("Modo AD exige AD_SERVIDOR, AD_USUARIO, AD_SENHA e AD_BASE_DN.")
        self._cfg = cfg
        self._server = Server(cfg.ad_servidor, use_ssl=cfg.ad_ssl, connect_timeout=5)

    def _conectar(self):
        from ldap3 import NTLM, SIMPLE, Connection

        auth = NTLM if "\\" in self._cfg.ad_usuario else SIMPLE
        return Connection(self._server, user=self._cfg.ad_usuario, password=self._cfg.ad_senha,
                          authentication=auth, auto_bind=True, raise_exceptions=True, receive_timeout=10)

    def _buscar(self, conn, email: str) -> dict | None:
        from ldap3 import BASE, SUBTREE
        from ldap3.utils.conv import escape_filter_chars

        e = escape_filter_chars(email.strip())
        conn.search(self._cfg.ad_base_dn,
                    f"(&(objectCategory=person)(objectClass=user)(|(userPrincipalName={e})(mail={e})))",
                    SUBTREE, attributes=["distinguishedName"], size_limit=2)
        achados = [r for r in conn.response if r.get("type") == "searchResEntry"]
        if not achados:
            return None
        dn = achados[0]["dn"]

        conn.search(dn, "(objectClass=*)", BASE, attributes=[
            "sAMAccountName", "displayName", "userAccountControl", "pwdLastSet", "badPwdCount", "lockoutTime",
            "msDS-User-Account-Control-Computed", "msDS-UserPasswordExpiryTimeComputed"])
        bruto = conn.response[0]["raw_attributes"]

        def inteiro(nome: str) -> int:
            return int(bruto[nome][0]) if bruto.get(nome) else 0

        def texto(nome: str) -> str:
            return bruto[nome][0].decode("utf-8") if bruto.get(nome) else ""

        return {
            "dn": dn,
            "login": texto("sAMAccountName"),
            "nome": texto("displayName") or texto("sAMAccountName"),
            "uac": inteiro("userAccountControl"),
            "uac_calculado": inteiro("msDS-User-Account-Control-Computed"),
            "pwd_last_set": inteiro("pwdLastSet"),
            "expira": inteiro("msDS-UserPasswordExpiryTimeComputed"),
            "bad_pwd": inteiro("badPwdCount"),
            "lockout_time": inteiro("lockoutTime"),
        }

    def obter_senha(self, email):
        with self._conectar() as conn:
            if not (u := self._buscar(conn, email)):
                return None
        alterada = _filetime(u["pwd_last_set"])
        if u["uac"] & UAC_SENHA_NUNCA_EXPIRA or u["expira"] >= FILETIME_NUNCA:
            return _info_senha(u["login"], u["nome"], alterada, None, nunca_expira=True)
        if u["pwd_last_set"] == 0 or u["expira"] == 0:
            return _info_senha(u["login"], u["nome"], alterada, _agora(), deve_trocar=True)
        return _info_senha(u["login"], u["nome"], alterada, _filetime(u["expira"]))

    def obter_status(self, email):
        with self._conectar() as conn:
            if not (u := self._buscar(conn, email)):
                return None
        bloqueada = bool(u["uac_calculado"] & UAC_BLOQUEADA)
        return _status(u["login"], u["nome"], not u["uac"] & UAC_DESABILITADA, bloqueada,
                       _filetime(u["lockout_time"]) if bloqueada else None, u["bad_pwd"])

    def desbloquear(self, email):
        from ldap3 import MODIFY_REPLACE

        with self._conectar() as conn:
            if not (u := self._buscar(conn, email)):
                return None
            if u["uac"] & UAC_DESABILITADA:
                return _desbloqueio(u["login"], False, MSG_DESABILITADA)
            if not u["uac_calculado"] & UAC_BLOQUEADA:
                return _desbloqueio(u["login"], False, MSG_NAO_BLOQUEADA)
            conn.modify(u["dn"], {"lockoutTime": [(MODIFY_REPLACE, ["0"])]})
            return _desbloqueio(u["login"], True, MSG_DESBLOQUEADA)


def criar_diretorio(cfg: Config) -> Diretorio:
    if cfg.diretorio_modo == "ad":
        return DiretorioActiveDirectory(cfg)
    if cfg.diretorio_modo == "mock":
        return DiretorioMock(cfg.usuarios_mock, cfg.politica_expiracao_dias)
    raise RuntimeError(f"DIRETORIO_MODO inválido: '{cfg.diretorio_modo}' (use 'mock' ou 'ad').")
