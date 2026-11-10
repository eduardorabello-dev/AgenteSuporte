import csv
import json
import logging
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime

from .motor import Motor, PlanilhaIndisponivel
from .registro import ArquivoEmUso
from .seguranca import linha_segura
from .texto import normalizar

log = logging.getLogger("suporte")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
SOBRA_DO_EMAIL = re.compile(r"^\s*(?:(?:eu\s+)?sou|meu\s+e-?mail\s+(?:é|e)|e-?mail\s*:)?\s*,?\s*(?:e\s+)?", re.I)

SAUDACAO = re.compile(r"^(oi+|ola|opa|bom dia|boa tarde|boa noite|e ai|hello|hey)\b[\s!.,?]*(tudo bem|td bem)?[\s!.,?]*$")
AJUDA = re.compile(r"^(ajuda|help|menu|\?|o que (voce|vc) (faz|sabe fazer)|como (funciona|usar))[\s!.?]*$")
RESOLVEU = re.compile(r"\b(resolveu|resolvido|funcionou|deu certo|consegui|obrigad[oa]|valeu|era isso|show|perfeito)\b")
NAO_RESOLVEU = re.compile(r"\b(nao (resolveu|funcionou|deu certo|consegui|era isso|adiantou)|continua|ainda (nao|esta|da)|persiste|"
                          r"mesmo problema|falar com (um )?(tecnico|humano|atendente|alguem))\b")
NOVO = re.compile(r"\b(outro problema|outra coisa|novo chamado|recomecar|reiniciar conversa|limpar)\b")
NUMERO = re.compile(r"^\s*(\d)\s*[).]?\s*$")
NOTA = re.compile(r"^\s*(?:nota\s*)?([1-5])\s*(?:estrelas?)?\s*[!.]?\s*$")
NOTAS = {1: "Péssimo", 2: "Ruim", 3: "Regular", 4: "Bom", 5: "Ótimo"}
MAX_COMENTARIO = 500

BOAS_VINDAS = (
    "Olá! Sou o assistente de suporte de TI. Me conte com suas palavras o que está acontecendo, por exemplo:\n"
    "- “minha senha expirou e não consigo entrar”\n"
    "- “a impressora do financeiro não imprime”\n"
    "- “a VPN não conecta de casa”\n\n"
    "Antes de começar, vou pedir seu **e-mail corporativo**: ele identifica você no atendimento. Se quiser, "
    "já mande junto, por exemplo: “sou nome@empresa.com e o Teams não abre”."
)

AJUDA_TEXTO = (
    "Posso ajudar assim:\n"
    "- **Descreva o problema** e eu indico a solução passo a passo.\n"
    "- Em problemas de **senha ou conta bloqueada**, verifico sua conta e, se der, desbloqueio na hora.\n"
    "- Se a solução não servir, digite o **número** de outra sugestão ou diga **\"não resolveu\"** que eu encaminho para um técnico.\n"
    "- Para começar outro assunto, diga **\"outro problema\"**."
)


@dataclass
class Sessao:
    id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    email: str = ""
    nome: str = ""
    pendente: str | None = None
    ultimo: dict | None = None
    ultima_descricao: str = ""
    outros_artigos: list = field(default_factory=list)
    protocolo: str | None = None
    encaminhado: bool = False
    solucao: str = ""
    a_avaliar: dict | None = None
    previsao: dict | None = None
    historico: list = field(default_factory=list)
    protocolo_encaminhado: str | None = None
    email_fixo: bool = False
    atualizada_em: datetime = field(default_factory=datetime.now)


def _resposta(texto: str, detalhes: dict | None = None) -> dict:
    return {"texto": texto, "detalhes": detalhes}


class Conversa:
    MAX_SESSOES = 500

    def __init__(self, motor: Motor):
        self.motor = motor
        self._sessoes: dict[str, Sessao] = {}
        self._trava = threading.Lock()
        self._contador = 0


    def existe(self, sessao_id: str) -> bool:
        with self._trava:
            return sessao_id in self._sessoes

    def sessao(self, sessao_id: str | None) -> Sessao:
        with self._trava:
            if sessao_id and sessao_id in self._sessoes:
                s = self._sessoes[sessao_id]
            else:
                s = Sessao(id=secrets.token_urlsafe(24))
                self._sessoes[s.id] = s
                if len(self._sessoes) > self.MAX_SESSOES:
                    for antigo in sorted(self._sessoes.values(), key=lambda x: x.atualizada_em)[:100]:
                        self._sessoes.pop(antigo.id, None)
            s.atualizada_em = datetime.now()
            return s

    def sessao_da_conta(self, sessao_id: str | None, email: str, nome: str) -> Sessao:
        with self._trava:
            atual = self._sessoes.get(sessao_id or "")
            if atual is not None and atual.email_fixo and atual.email != email:
                sessao_id = None
        s = self.sessao(sessao_id)
        if not s.email_fixo:
            s.email, s.nome, s.email_fixo = email, (nome.split() or [""])[0], True
            self.motor.colaboradores.registrar_contato(email, nome)
        return s

    def sessao_do_email(self, email: str) -> Sessao | None:
        with self._trava:
            dela = [s for s in self._sessoes.values() if s.email_fixo and s.email == email]
        return max(enumerate(dela), key=lambda par: (par[1].atualizada_em, par[0]))[1] if dela else None

    def _novo_protocolo(self) -> str:
        with self._trava:
            self._contador += 1
            return f"CH-{datetime.now():%Y%m%d-%H%M%S}-{self._contador:03d}"

    def _registrar_encaminhamento(self, sessao: Sessao, protocolo: str, r: dict, motivo: str) -> dict | None:
        sessao.protocolo_encaminhado = protocolo
        self.motor.atendimentos.registrar("encaminhado", protocolo=protocolo, email=sessao.email,
                                          categoria=r.get("categoria", ""), urgencia=r.get("urgencia", ""),
                                          solucao=sessao.solucao, texto=motivo)
        if sessao.email:
            self.motor.colaboradores.registrar_chamado(sessao.email, protocolo)
        linha = {
            "protocolo": protocolo, "email": sessao.email, "sessao": sessao.id,
            "historico_chat": json.dumps(sessao.historico, ensure_ascii=False),
            "descricao": sessao.ultima_descricao, "categoria": r.get("categoria", ""), "urgencia": r.get("urgencia", ""),
            "motivo": motivo,
            "acoes_executadas": " | ".join(f"{a['acao']}: {a['resultado']}" for a in r.get("acoes_executadas", [])),
        }
        try:
            equipe = [t["email"] for t in self.motor.contas.equipe()]
            previsao = self.motor.registro.registrar(linha, equipe)
            previsao["tecnico"] = self.motor.contas.nome(previsao["tecnico"]) if previsao["tecnico"] else ""
            sessao.previsao = previsao
        except ArquivoEmUso:
            log.exception("Não foi possível registrar o chamado %s", protocolo)
            sessao.previsao = None
        return sessao.previsao


    def _anotar(self, sessao: Sessao, evento: dict) -> None:
        sessao.historico.append({"hora": f"{datetime.now():%H:%M}"} | evento)
        del sessao.historico[:-60]
        self._sincronizar(sessao)

    def _sincronizar(self, sessao: Sessao) -> None:
        if not sessao.protocolo_encaminhado:
            return
        try:
            self.motor.registro.atualizar_historico(sessao.protocolo_encaminhado,
                                                    json.dumps(sessao.historico, ensure_ascii=False))
        except ArquivoEmUso:
            log.warning("Histórico do chamado %s não atualizado: CSV aberto no Excel", sessao.protocolo_encaminhado)

    def _novo_problema(self, sessao: Sessao) -> None:
        sessao.historico, sessao.protocolo_encaminhado = [], None

    def marcar_passos(self, sessao: Sessao, titulo: str, feitos: list[int]) -> bool:
        solucao = next((e for e in reversed(sessao.historico) if e["tipo"] == "solucao" and e["titulo"] == titulo), None)
        if solucao is None:
            return False
        solucao["feitos"] = sorted({i for i in feitos if 0 <= i < len(solucao["passos"])})
        self._sincronizar(sessao)
        return True

    @staticmethod
    def _texto_previsao(previsao: dict | None) -> str:
        if previsao is None:
            return ("**Atenção:** não consegui gravar o registro porque o arquivo de chamados está aberto no Excel. "
                    "Avise a equipe técnica.")
        fila = f" Há {previsao['na_frente']} chamado(s) na frente do seu." if previsao["na_frente"] else ""
        quem = f" Técnico responsável: **{previsao['tecnico']}**." if previsao.get("tecnico") else ""
        return (f"Previsão para um técnico te chamar: **cerca de {previsao['texto']}** (até as {previsao['ate']})."
                + fila + quem)

    def _gravar_csv(self, arquivo, campos: list[str], linha: dict) -> None:
        with self._trava:
            novo = not arquivo.exists()
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            with arquivo.open("a", newline="", encoding="utf-8-sig" if novo else "utf-8") as f:
                escritor = csv.DictWriter(f, fieldnames=campos, delimiter=";")
                if novo:
                    escritor.writeheader()
                escritor.writerow(linha_segura(linha))


    def avaliar(self, sessao: Sessao, nota: int, comentario: str = "", protocolo: str | None = None) -> dict:
        alvo = sessao.a_avaliar
        if not alvo or (protocolo and protocolo != alvo["protocolo"]):
            raise ValueError("Não há atendimento resolvido esperando avaliação.")
        if not 1 <= nota <= 5:
            raise ValueError("A nota vai de 1 a 5.")
        comentario = " ".join((comentario or "").split())[:MAX_COMENTARIO]
        try:
            self._gravar_csv(self.motor.cfg.avaliacoes,
                             ["data", "protocolo", "email", "categoria", "solucao", "descricao", "nota", "comentario"],
                             {"data": f"{datetime.now():%d/%m/%Y %H:%M}", "email": sessao.email, "nota": nota,
                              "comentario": comentario, **alvo})
        except PermissionError:
            raise ValueError("o arquivo avaliacoes.csv está aberto no Excel; feche-o e tente de novo.")
        sessao.a_avaliar = None
        agradecimento = "Obrigado pela avaliação!" if nota >= 4 else \
            "Obrigado pela avaliação. Vamos usar sua opinião para melhorar o atendimento."
        return _resposta(f"{agradecimento} Se precisar de mais alguma coisa, é só escrever.",
                         {"tipo": "avaliado", "nota": nota, "rotulo": NOTAS[nota]})


    def boas_vindas(self, sessao: Sessao | None = None) -> dict:
        if sessao is not None and sessao.email_fixo:
            nome = f", {sessao.nome}" if sessao.nome else ""
            return _resposta(BOAS_VINDAS.split("\n\n")[0].replace("Olá!", f"Olá{nome}!", 1)
                             + f"\n\nVocê está atendido como **{sessao.email}**.")
        return _resposta(BOAS_VINDAS)

    def responder(self, sessao: Sessao, mensagem: str) -> dict:
        mensagem = re.sub(r"[﻿​‌‍]", "", mensagem or "").strip()
        if not mensagem:
            return _resposta("Pode escrever o que está acontecendo?")
        t = normalizar(mensagem)

        if conversa := self.motor.mensagens.ativa_da_sessao(sessao.id):
            protocolo, _ = conversa
            autor = sessao.nome or sessao.email or "Usuário"
            m = self.motor.mensagens.enviar(protocolo, "usuario", autor, mensagem)
            return _resposta("", {"tipo": "para_tecnico", "mensagem": m})

        so_email = not sessao.email_fixo and bool(EMAIL.search(mensagem)) and len(
            normalizar(SOBRA_DO_EMAIL.sub("", EMAIL.sub("", mensagem).strip(" ,.;:-"))).split()) <= 2
        if NOVO.search(t):
            self._novo_problema(sessao)
        elif not so_email:
            self._anotar(sessao, {"tipo": "mensagem", "texto": mensagem[:500]})

        achou_email = None if sessao.email_fixo else EMAIL.search(mensagem)
        if achou_email:
            self._definir_email(sessao, achou_email.group(0).lower())
            resto = SOBRA_DO_EMAIL.sub("", EMAIL.sub("", mensagem).strip(" ,.;:-")).strip(" ,.;:-")
            if sessao.pendente:
                descricao, sessao.pendente = sessao.pendente, None
                if resto and len(normalizar(resto).split()) > 2:
                    descricao = f"{descricao}. {resto}"
                return self._atender(sessao, descricao)
            if len(normalizar(resto).split()) <= 2:
                return _resposta(f"Anotei seu e-mail ({sessao.email}). Agora me conte o problema.")
            mensagem, t = resto, normalizar(resto)

        if sessao.pendente and not achou_email and not (SAUDACAO.match(t) or AJUDA.match(t) or NOVO.search(t)):
            if len(t.split()) > 3:
                sessao.pendente = f"{sessao.pendente}. {mensagem}"
            return _resposta("Preciso do seu **e-mail corporativo** para continuar (por exemplo, "
                             "nome.sobrenome@empresa.com). Assim que você informar, eu sigo com o seu problema.",
                             {"tipo": "pedir_email"})

        if SAUDACAO.match(t):
            return _resposta(("Olá" + (f", {sessao.nome}" if sessao.nome else "") + "! Em que posso ajudar? "
                              "Descreva o problema com suas palavras."))
        if AJUDA.match(t):
            return _resposta(AJUDA_TEXTO)
        if NOVO.search(t):
            sessao.ultimo, sessao.outros_artigos, sessao.pendente, sessao.protocolo = None, [], None, None
            sessao.encaminhado = False
            return _resposta("Certo, vamos para outro assunto. O que está acontecendo?")

        if sessao.encaminhado and NAO_RESOLVEU.search(t):
            previsao = f" A previsão de contato é até as **{sessao.previsao['ate']}**." if sessao.previsao else ""
            return _resposta(f"Seu chamado **{sessao.protocolo}** já está registrado para a equipe técnica, que vai "
                             f"entrar em contato.{previsao} Se for outro assunto, diga **\"outro problema\"**.")

        if sessao.a_avaliar and not sessao.ultimo and (nota := NOTA.match(t)):
            return self.avaliar(sessao, int(nota.group(1)))

        if n := NUMERO.match(t):
            if sessao.outros_artigos:
                return self._mostrar_outro_artigo(sessao, int(n.group(1)))
            if sessao.ultimo:
                return _resposta("Para esse problema não tenho outras sugestões. Responda **\"resolveu\"** ou "
                                 "**\"não resolveu\"**, ou descreva o problema com mais detalhes.")

        if sessao.ultimo:
            if NAO_RESOLVEU.search(t):
                return self._encaminhar(sessao, "a solução sugerida não resolveu")
            if RESOLVEU.search(t) and len(t.split()) <= 6:
                return self._resolvido(sessao)
        elif RESOLVEU.search(t) and len(t.split()) <= 4:
            return _resposta("Por nada! Se precisar de ajuda, é só descrever o problema.")

        return self._atender(sessao, mensagem)


    def _definir_email(self, sessao: Sessao, email: str) -> None:
        novo = email != sessao.email
        sessao.email = email
        try:
            status = self.motor.diretorio.obter_status(email)
        except Exception:
            status = None
        if status:
            sessao.nome = status["nome"].split()[0]
        if novo:
            self.motor.colaboradores.registrar_contato(email, status["nome"] if status else "")

    def _atender(self, sessao: Sessao, descricao: str) -> dict:
        try:
            atendimento = self.motor.atendimento()
        except PlanilhaIndisponivel as e:
            return _resposta(f"Não consegui carregar a planilha de chamados: {e}. Avise o administrador.")

        if not sessao.email:
            sessao.pendente = descricao
            conta = self.motor.regras.casa(self.motor.regras.gatilho_conta, normalizar(descricao))
            motivo = ("Parece algo com sua senha ou conta: com o e-mail eu também verifico sua conta."
                      if conta else "Assim registro o atendimento no seu nome e a equipe técnica consegue falar com você.")
            return _resposta(f"Entendi o problema. Antes de continuar, qual é o seu **e-mail corporativo**? {motivo}",
                             {"tipo": "pedir_email"})

        chamado = {"id": self._novo_protocolo(), "nome": sessao.nome, "email": sessao.email, "descricao": descricao}
        r = atendimento.processar(chamado)
        artigos = [a for a in self.motor.kb.artigos if a["id"] in r["artigos_utilizados"]]
        artigos.sort(key=lambda a: r["artigos_utilizados"].index(a["id"]))

        if not artigos and not r["acoes_executadas"] and r["categoria"] == "Não classificado":
            self.motor.atendimentos.registrar("nao_entendido", email=sessao.email, texto=descricao)
            return _resposta("Não consegui entender bem o problema. Pode descrever de outro jeito, dizendo **o que** "
                             "não funciona e **o que aparece** na tela? Ex.: \"o Outlook não abre e dá erro\".")

        if sessao.encaminhado:
            if sessao.historico and sessao.historico[-1].get("texto") == descricao[:500]:
                sessao.historico.pop()
                self._sincronizar(sessao)
            self._novo_problema(sessao)
            self._anotar(sessao, {"tipo": "mensagem", "texto": descricao[:500]})
        sessao.ultimo, sessao.protocolo, sessao.ultima_descricao = r, r["chamado_id"], descricao
        sessao.encaminhado = False
        self.motor.atendimentos.registrar("atendido", protocolo=r["chamado_id"], email=sessao.email,
                                          categoria=r["categoria"], urgencia=r["urgencia"],
                                          solucao=artigos[0]["titulo"] if artigos else "")
        if artigos:
            self._anotar(sessao, {"tipo": "solucao", "titulo": artigos[0]["titulo"],
                                  "passos": artigos[0]["solucao"], "feitos": []})
        sessao.outros_artigos = artigos[1:]
        sessao.solucao = artigos[0]["titulo"] if artigos else ""
        detalhes = {
            "tipo": "atendimento",
            "categoria": r["categoria"], "urgencia": r["urgencia"], "protocolo": r["chamado_id"],
            "encaminhado": r["escalar_para_humano"], "motivo": r["motivo_escalonamento"],
            "correcoes": r["correcoes_busca"],
            "conta": [f"{a['resultado'][:1].upper()}{a['resultado'][1:]}" for a in r["acoes_executadas"]],
            "passos": {"titulo": artigos[0]["titulo"], "itens": artigos[0]["solucao"]} if artigos else None,
            "outros": [] if r["escalar_para_humano"] else
                      [{"numero": i, "titulo": a["titulo"]} for i, a in enumerate(sessao.outros_artigos, 2)],
        }

        partes = []
        if r["correcoes_busca"]:
            partes.append("(Entendi " + ", ".join(f"\"{a}\" como \"{b}\"" for a, b in r["correcoes_busca"].items()) + ".)")
        partes.append(f"Entendi: é um problema de **{r['categoria']}**, urgência **{r['urgencia']}**.")

        if r["acoes_executadas"]:
            partes.append("Verifiquei sua conta:\n" + "\n".join(
                f"- {a['resultado'][:1].upper()}{a['resultado'][1:]}" for a in r["acoes_executadas"]))

        if artigos:
            principal = artigos[0]
            passos = "\n".join(f"{i}. {p}" for i, p in enumerate(principal["solucao"], 1))
            partes.append(f"Tente isto (**{principal['titulo']}**):\n{passos}")

        if r["escalar_para_humano"]:
            previsao = self._registrar_encaminhamento(sessao, r["chamado_id"], r, r["motivo_escalonamento"])
            detalhes["previsao"] = previsao
            sessao.ultimo, sessao.encaminhado = None, True
            partes.append(f"Também **registrei seu chamado para a equipe técnica** ({r['motivo_escalonamento']}). "
                          f"Seu protocolo é **{r['chamado_id']}**.")
            partes.append(self._texto_previsao(previsao))
        else:
            if sessao.outros_artigos:
                opcoes = "\n".join(f"{i}. {a['titulo']}" for i, a in enumerate(sessao.outros_artigos, 2))
                partes.append(f"Se não for isso, posso mostrar (digite o número):\n{opcoes}")
            partes.append("Isso resolveu? Responda **\"resolveu\"** ou **\"não resolveu\"**.")

        return _resposta("\n\n".join(partes), detalhes)

    def _resolvido(self, sessao: Sessao) -> dict:
        r = sessao.ultimo or {}
        sessao.a_avaliar = {"protocolo": sessao.protocolo or "", "categoria": r.get("categoria", ""),
                            "solucao": sessao.solucao, "descricao": sessao.ultima_descricao}
        self.motor.atendimentos.registrar("resolvido", protocolo=sessao.protocolo or "", email=sessao.email,
                                          categoria=r.get("categoria", ""), solucao=sessao.solucao)
        sessao.ultimo, sessao.outros_artigos = None, []
        self._novo_problema(sessao)
        return _resposta("Que bom que resolveu! Se quiser, dê uma **nota de 1 a 5** para este atendimento "
                         "(5 = ótimo). Se precisar de mais alguma coisa, é só escrever.",
                         {"tipo": "resolvido", "protocolo": sessao.protocolo, "categoria": r.get("categoria")})

    def _mostrar_outro_artigo(self, sessao: Sessao, numero: int) -> dict:
        indice = numero - 2
        if not 0 <= indice < len(sessao.outros_artigos):
            faixa = f"2 a {len(sessao.outros_artigos) + 1}" if len(sessao.outros_artigos) > 1 else "2"
            return _resposta(f"Não tenho a opção {numero}. Digite {faixa}, ou descreva o problema de novo.")
        a = sessao.outros_artigos[indice]
        sessao.solucao = a["titulo"]
        self._anotar(sessao, {"tipo": "solucao", "titulo": a["titulo"], "passos": a["solucao"], "feitos": []})
        passos = "\n".join(f"{i}. {p}" for i, p in enumerate(a["solucao"], 1))
        return _resposta(f"**{a['titulo']}**:\n{passos}\n\nIsso resolveu? Responda **\"resolveu\"** ou **\"não resolveu\"**.",
                         {"tipo": "artigo", "passos": {"titulo": a["titulo"], "itens": a["solucao"]}})

    def _encaminhar(self, sessao: Sessao, motivo: str) -> dict:
        protocolo = sessao.protocolo or self._novo_protocolo()
        r = sessao.ultimo or {}
        previsao = self._registrar_encaminhamento(sessao, protocolo, r, motivo)
        sessao.ultimo, sessao.outros_artigos, sessao.encaminhado = None, [], True
        resumo = f" ({r.get('categoria')}, urgência {r.get('urgencia')})" if r else ""
        return _resposta(f"Sinto muito que não resolveu. **Registrei seu chamado {protocolo}{resumo} para a equipe "
                         f"técnica**, que vai entrar em contato. Motivo: {motivo}.\n\n{self._texto_previsao(previsao)}",
                         {"tipo": "encaminhado", "protocolo": protocolo, "encaminhado": True, "motivo": motivo,
                          "categoria": r.get("categoria"), "urgencia": r.get("urgencia"), "previsao": previsao})
