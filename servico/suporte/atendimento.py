import logging
from datetime import datetime

from .base_conhecimento import BaseConhecimento
from .classificador import Classificador, Regras
from .diretorio import Diretorio
from .texto import normalizar

log = logging.getLogger("suporte")

DIAS_AVISO_SENHA = 15


def _data(valor: datetime | None) -> str:
    return valor.strftime("%d/%m/%Y às %H:%M") if valor else "-"


def _texto_senha(info: dict) -> str:
    if info["nunca_expira"]:
        return "Sua senha está configurada para não expirar."
    if info["expirada"]:
        return f"Sua senha expirou em {_data(info['senha_expira_em'])} e precisa ser trocada."
    if info["dias_restantes"] <= DIAS_AVISO_SENHA:
        return f"Sua senha expira em {_data(info['senha_expira_em'])} (faltam {info['dias_restantes']} dia(s))."
    return f"Sua senha está válida até {_data(info['senha_expira_em'])}."


class Atendimento:
    def __init__(self, classificador: Classificador, kb: BaseConhecimento, diretorio: Diretorio, regras: Regras):
        self.classificador = classificador
        self.kb = kb
        self.diretorio = diretorio
        self.regras = regras

    def processar(self, chamado: dict, somente_triagem: bool = False) -> dict:
        assunto = (chamado.get("assunto") or "").strip()
        descricao = (chamado.get("descricao") or "").strip()
        texto = f"{assunto}. {descricao}" if assunto else descricao

        triagem = self.classificador.classificar(texto, descricao)
        resultado = {"chamado_id": chamado.get("id"), "solicitante": chamado.get("email"), **triagem}
        if somente_triagem:
            return resultado

        busca = self.kb.buscar(texto, categoria=triagem["categoria"])
        artigos = busca["artigos"]
        acoes, verificacoes, motivos = [], [], []

        if triagem["urgencia"] == "Crítica":
            motivos.append("urgência crítica: vários usuários ou operação parada")
        if triagem["incidente_seguranca"]:
            motivos.append("possível incidente de segurança: o time de Segurança precisa avaliar")
        if triagem["categoria"] in self.regras.escalar_categorias:
            motivos.append(self.regras.motivo_escalar_categoria)
        if not artigos:
            motivos.append("nenhum artigo da base de conhecimento corresponde ao problema")

        if self.regras.casa(self.regras.gatilho_conta, normalizar(texto)):
            self._acoes_de_conta(chamado.get("email") or "", texto, triagem, acoes, verificacoes, motivos)

        escalar = bool(motivos)
        resultado.update({
            "artigos_utilizados": [a["id"] for a in artigos],
            "solucao_sugerida": artigos[0]["passos"] if artigos else [],
            "correcoes_busca": busca["correcoes"],
            "acoes_executadas": acoes,
            "resolvido_automaticamente": not escalar,
            "escalar_para_humano": escalar,
            "motivo_escalonamento": "; ".join(motivos),
        })
        resultado["resposta_usuario"] = self._resposta(chamado, resultado, artigos, verificacoes)
        return resultado

    def _acoes_de_conta(self, email: str, texto: str, triagem: dict, acoes: list, verificacoes: list,
                        motivos: list) -> None:
        if not email:
            motivos.append("chamado de acesso sem e-mail do solicitante")
            return
        try:
            senha = self.diretorio.obter_senha(email)
            status = self.diretorio.obter_status(email)
        except Exception as erro:
            log.exception("Falha ao consultar o diretório para %s", email)
            acoes.append({"acao": "consultar diretório", "resultado": f"falhou: {erro}"})
            motivos.append("não foi possível consultar o diretório")
            return
        if senha is None or status is None:
            acoes.append({"acao": "consultar diretório", "resultado": "usuário não encontrado"})
            motivos.append(f"o e-mail {email} não foi encontrado no diretório")
            return

        acoes.append({"acao": "checar expiração de senha", "resultado": _texto_senha(senha)})
        verificacoes.append(_texto_senha(senha))
        situacao = "bloqueada" if status["bloqueada"] else "desbloqueada"
        if not status["habilitada"]:
            situacao = "desabilitada"
        acoes.append({"acao": "verificar status da conta",
                      "resultado": f"conta {situacao}, {status['tentativas_invalidas']} tentativa(s) inválida(s)"})

        if not status["habilitada"]:
            verificacoes.append("Sua conta está desabilitada; a reativação precisa de aprovação do seu gestor.")
            motivos.append("conta desabilitada")
            return
        if not status["bloqueada"]:
            verificacoes.append("Sua conta não está bloqueada.")
            return
        pediu = self.regras.casa(self.regras.pedido_desbloqueio, normalizar(texto))
        if triagem["incidente_seguranca"] or not pediu:
            verificacoes.append("Sua conta está bloqueada; um técnico vai avaliar antes de desbloquear.")
            motivos.append("conta bloqueada sem pedido de desbloqueio claro ou com suspeita de segurança")
            return
        try:
            r = self.diretorio.desbloquear(email)
        except Exception as erro:
            log.exception("Falha ao desbloquear %s", email)
            acoes.append({"acao": "desbloquear conta", "resultado": f"falhou: {erro}"})
            motivos.append("o desbloqueio automático falhou")
            return
        acoes.append({"acao": "desbloquear conta", "resultado": r["mensagem"] if r else "usuário não encontrado"})
        if r and r["desbloqueada"]:
            verificacoes.append("Sua conta estava bloqueada e foi desbloqueada agora. Tente entrar novamente.")
        else:
            motivos.append("o desbloqueio automático não foi concluído")

    @staticmethod
    def _resposta(chamado: dict, r: dict, artigos: list, verificacoes: list) -> str:
        nome = (chamado.get("nome") or "").split()
        linhas = [f"Olá, {nome[0]}!" if nome else "Olá!", ""]
        ident = f"Seu chamado {r['chamado_id']}" if r.get("chamado_id") else "Seu chamado"
        linhas.append(f"{ident} foi classificado como {r['categoria']}, urgência {r['urgencia']}.")
        if verificacoes:
            linhas += ["", "O que verificamos na sua conta:", *[f"- {v}" for v in verificacoes]]
        if artigos:
            linhas += ["", f"Siga estes passos ({artigos[0]['id']} - {artigos[0]['titulo']}):"]
            linhas += [f"{i}. {p}" for i, p in enumerate(artigos[0]["passos"], 1)]
        if r["escalar_para_humano"]:
            linhas += ["", "Encaminhamos seu chamado para um técnico, que vai entrar em contato. "
                           f"Motivo: {r['motivo_escalonamento']}."]
        else:
            linhas += ["", "Se os passos não resolverem, responda este chamado que um técnico vai ajudar."]
        return "\n".join(linhas)
