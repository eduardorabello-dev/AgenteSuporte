import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import CONHECIMENTO, PAGINA_CHAT, PAGINA_INICIO, PAGINA_PAINEL, VISUAL, Config
from .contas import DURACAO_SESSAO_SEGUNDOS, Contas, LoginBloqueado, SenhaFraca
from .contas import Sessao as SessaoConta
from .conversa import Conversa
from .diretorio import Diretorio
from .estatisticas import indicadores, ler_avaliacoes
from .motor import Motor
from .registro import STATUS, ArquivoEmUso
from .seguranca import proteger


class JsonUtf8(JSONResponse):
    media_type = "application/json; charset=utf-8"


class MensagemChat(BaseModel):
    sessao: str | None = Field(None, max_length=64)
    mensagem: str = Field("", max_length=2000)


class Avaliacao(BaseModel):
    sessao: str = Field(max_length=64)
    protocolo: str | None = None
    nota: int = Field(ge=1, le=5)
    comentario: str = Field("", max_length=2000)


class AtualizacaoChamado(BaseModel):
    status: str | None = None
    tecnico: str | None = Field(None, max_length=200)
    observacao: str | None = Field(None, max_length=1000)


class Login(BaseModel):
    email: str = Field(max_length=200)
    senha: str = Field(max_length=200)


class TrocaSenha(BaseModel):
    atual: str = Field(max_length=200)
    nova: str = Field(max_length=200)


class Digitando(BaseModel):
    sessao: str = Field(max_length=64)


class PassosMarcados(BaseModel):
    sessao: str = Field(max_length=64)
    titulo: str = Field(max_length=300)
    feitos: list[int] = Field(default_factory=list, max_length=50)


class TextoMensagem(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class NovaConta(BaseModel):
    tipo: str = Field(pattern="^(tecnico|colaborador)$")
    email: str = Field(max_length=200)
    nome: str = Field(min_length=2, max_length=100)
    admin: bool = False


class AcaoConta(BaseModel):
    tipo: str = Field(pattern="^(tecnico|colaborador)$")
    email: str = Field(max_length=200)
    ativo: bool = True


COOKIE_TECNICO = "sessao_tecnico"
COOKIE_COLABORADOR = "sessao_colaborador"


def pagina(caminho: Path) -> FileResponse:
    return FileResponse(caminho, media_type="text/html; charset=utf-8")


def criar_app(cfg: Config, diretorio: Diretorio | None = None) -> FastAPI:
    motor = Motor(cfg, diretorio)
    conversa = Conversa(motor)

    app = FastAPI(title="Suporte de TI", default_response_class=JsonUtf8, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.middleware("http")(proteger)

    @app.get("/", include_in_schema=False)
    def pagina_inicial():
        return pagina(PAGINA_INICIO / "index.html")


    def rotas_de_login(prefixo: str, contas: Contas, cookie: str, extra=lambda s: {}):

        def sessao_atual(request: Request) -> SessaoConta | None:
            automatica = request.headers.get("x-consulta-automatica") == "1"
            return contas.sessao(request.cookies.get(cookie), renovar=not automatica)

        def exigir_login(request: Request) -> SessaoConta:
            s = sessao_atual(request)
            if s is None:
                raise HTTPException(401, "Entre com seu e-mail e senha.")
            if s.trocar_senha:
                raise HTTPException(403, "Troque a senha provisória para continuar.")
            return s

        def perfil(s: SessaoConta) -> dict:
            return contas.perfil(s.email) | {"trocar_senha": s.trocar_senha} | extra(s)

        @app.get(f"{prefixo}/eu", name=f"eu{prefixo}")
        def eu(request: Request):
            s = sessao_atual(request)
            if s is None:
                raise HTTPException(401, "Entre com seu e-mail e senha.")
            return perfil(s)

        @app.post(f"{prefixo}/entrar", name=f"entrar{prefixo}")
        def entrar(dados: Login, response: Response):
            try:
                s = contas.entrar(dados.email, dados.senha)
            except LoginBloqueado as e:
                raise HTTPException(429, str(e))
            except PermissionError as e:
                raise HTTPException(401, str(e))
            response.set_cookie(cookie, s.token, httponly=True, samesite="strict", path="/",
                                max_age=DURACAO_SESSAO_SEGUNDOS)
            return perfil(s)

        @app.post(f"{prefixo}/senha", name=f"senha{prefixo}")
        def trocar_senha(dados: TrocaSenha, request: Request):
            s = sessao_atual(request)
            if s is None:
                raise HTTPException(401, "Sua sessão expirou. Entre de novo.")
            try:
                contas.trocar_senha(s, dados.atual, dados.nova)
            except SenhaFraca as e:
                raise HTTPException(422, str(e))
            except PermissionError as e:
                raise HTTPException(401, str(e))
            return perfil(s)

        @app.post(f"{prefixo}/sair", name=f"sair{prefixo}")
        def sair(request: Request, response: Response):
            contas.sair(request.cookies.get(cookie))
            response.delete_cookie(cookie, path="/")
            return {"ok": True}

        return sessao_atual, exigir_login

    contas = motor.contas
    contas_colab = motor.contas_colaboradores
    _, colaborador_logado = rotas_de_login("/chat", contas_colab, COOKIE_COLABORADOR)
    _, tecnico_logado = rotas_de_login("/tecnico", contas, COOKIE_TECNICO, lambda s: {"equipe": contas.equipe()})


    msgs = motor.mensagens

    @app.get("/chat", include_in_schema=False)
    def pagina_chat():
        return pagina(PAGINA_CHAT / "index.html")

    def sessao_da_conta(sessao_id: str | None, s: SessaoConta):
        return conversa.sessao_da_conta(sessao_id, s.email, contas_colab.nome(s.email))

    def sessao_existente(sessao_id: str, s: SessaoConta):
        if not conversa.existe(sessao_id):
            return None
        sessao = conversa.sessao(sessao_id)
        return sessao if sessao.email_fixo and sessao.email == s.email else None

    @app.post("/chat")
    def chat(m: MensagemChat, s: SessaoConta = Depends(colaborador_logado)):
        sessao = sessao_da_conta(m.sessao, s)
        resposta = conversa.boas_vindas(sessao) if not m.mensagem.strip() else conversa.responder(sessao, m.mensagem)
        return {"sessao": sessao.id, **resposta}

    @app.post("/avaliacao")
    def avaliacao(a: Avaliacao, s: SessaoConta = Depends(colaborador_logado)):
        sessao = sessao_da_conta(a.sessao, s)
        try:
            resposta = conversa.avaliar(sessao, a.nota, a.comentario, a.protocolo)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"sessao": sessao.id, **resposta}

    @app.get("/chat/problemas-comuns")
    def problemas_comuns():
        bruto = json.loads((CONHECIMENTO / "problemas-comuns.json").read_text(encoding="utf-8"))
        return {"grupos": [{"tema": g["tema"], "problemas": [{"texto": p["texto"], "destaque": p.get("destaque", False)}
                                                            for p in g["problemas"]]} for g in bruto["grupos"]]}

    @app.get("/chat/mensagens")
    def mensagens_do_chat(sessao: str, desde: int = 0, s: SessaoConta = Depends(colaborador_logado)):
        if sessao_existente(sessao, s) is None:
            return {"mensagens": [], "conversa": None, "tecnico_digitando": False}
        msgs.marcar_visto(sessao)
        ativa = msgs.ativa_da_sessao(sessao)
        return {
            "mensagens": msgs.da_sessao(sessao, desde),
            "conversa": {"protocolo": ativa[0], "tecnico": ativa[1]["tecnico_nome"]} if ativa else None,
            "tecnico_digitando": bool(ativa) and msgs.digitando(ativa[0], "tecnico"),
        }

    @app.post("/chat/passos")
    def passos_marcados(p: PassosMarcados, s: SessaoConta = Depends(colaborador_logado)):
        sessao = sessao_existente(p.sessao, s)
        if sessao is None:
            raise HTTPException(404, "Conversa não encontrada.")
        return {"ok": conversa.marcar_passos(sessao, p.titulo, p.feitos)}

    @app.post("/chat/digitando")
    def usuario_digitando(d: Digitando, s: SessaoConta = Depends(colaborador_logado)):
        if sessao_existente(d.sessao, s) and (ativa := msgs.ativa_da_sessao(d.sessao)):
            msgs.avisar_digitando(ativa[0], "usuario")
        return {"ok": True}

    @app.get("/chat/meus-chamados")
    def meus_chamados(s: SessaoConta = Depends(colaborador_logado)):
        try:
            dela = [c for c in motor.registro.listar() if c["email"] == s.email]
        except ArquivoEmUso as e:
            raise HTTPException(409, str(e))
        campos = ("protocolo", "data", "categoria", "urgencia", "status", "descricao", "motivo", "previsao",
                  "atualizado_em")
        return {"chamados": [{k: c[k] for k in campos} | {
            "tecnico": contas.nome(c["tecnico"]) if c["tecnico"] else "",
            "conversa_ativa": msgs.ativa(c["protocolo"]) is not None,
            "mensagens": msgs.listar(c["protocolo"]),
        } for c in reversed(dela)]}


    @app.get("/tecnico", include_in_schema=False)
    def pagina_tecnico():
        return pagina(PAGINA_PAINEL / "index.html")

    def sessao_viva(c: dict) -> str:
        original = c.get("sessao", "")
        if original and conversa.existe(original):
            return original
        recente = conversa.sessao_do_email(c.get("email", "")) if c.get("email") else None
        return recente.id if recente else ""
    def situacao_chat(c: dict) -> dict:
        sessao = sessao_viva(c)
        mensagens = msgs.listar(c["protocolo"])
        do_usuario = [m["id"] for m in mensagens if m["autor"] == "usuario"]
        return {"disponivel": bool(sessao), "online": msgs.online(sessao),
                "ativa": msgs.ativa(c["protocolo"]) is not None, "total": len(mensagens),
                "ultima_do_usuario": do_usuario[-1] if do_usuario else 0}

    def historico(c: dict) -> list:
        try:
            eventos = json.loads(c.get("historico_chat") or "[]")
        except ValueError:
            return []
        return eventos if isinstance(eventos, list) else []

    def publico(c: dict) -> dict:
        return ({k: v for k, v in c.items() if k not in ("sessao", "historico_chat")}
                | {"chat": situacao_chat(c), "historico": historico(c)})

    def chamado(protocolo: str) -> dict:
        try:
            achado = next((c for c in motor.registro.listar() if c["protocolo"] == protocolo), None)
        except ArquivoEmUso as e:
            raise HTTPException(409, str(e))
        if achado is None:
            raise HTTPException(404, f"Chamado {protocolo} não encontrado.")
        return achado

    @app.get("/tecnico/chamados")
    def listar_chamados(s: SessaoConta = Depends(tecnico_logado)):
        try:
            chamados = [publico(c) for c in motor.registro.listar()]
        except ArquivoEmUso as e:
            raise HTTPException(409, str(e))
        return {"chamados": chamados, "status": list(STATUS), "equipe": contas.equipe()}


    def estado_conversa(c: dict, desde: int) -> dict:
        ativa = msgs.ativa(c["protocolo"])
        return {"mensagens": msgs.listar(c["protocolo"], desde), "chat": situacao_chat(c),
                "tecnico": ativa["tecnico_nome"] if ativa else None,
                "usuario_digitando": bool(ativa) and msgs.digitando(c["protocolo"], "usuario")}

    @app.get("/tecnico/chamados/{protocolo}/conversa")
    def ver_conversa(protocolo: str, desde: int = 0, s: SessaoConta = Depends(tecnico_logado)):
        return estado_conversa(chamado(protocolo), desde)

    @app.post("/tecnico/chamados/{protocolo}/conversa")
    def iniciar_conversa(protocolo: str, s: SessaoConta = Depends(tecnico_logado)):
        c = chamado(protocolo)
        sessao = sessao_viva(c)
        if not sessao:
            raise HTTPException(409, "A pessoa não está mais com o chat aberto. Fale com ela pelo e-mail.")
        if c["status"] == "Concluído":
            raise HTTPException(409, "O chamado está concluído. Reabra-o para conversar.")
        msgs.iniciar(protocolo, sessao, s.email, contas.nome(s.email))
        if c["tecnico"] != s.email or c["status"] != "Em atendimento":
            try:
                motor.registro.atualizar(protocolo, status="Em atendimento", tecnico=s.email, por=s.email)
            except ArquivoEmUso:
                pass
        return estado_conversa(chamado(protocolo), 0)

    @app.post("/tecnico/chamados/{protocolo}/conversa/mensagem")
    def mensagem_do_tecnico(protocolo: str, t: TextoMensagem, s: SessaoConta = Depends(tecnico_logado)):
        if msgs.ativa(protocolo) is None:
            raise HTTPException(409, "Inicie a conversa antes de enviar mensagens.")
        try:
            return msgs.enviar(protocolo, "tecnico", contas.nome(s.email), t.texto)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post("/tecnico/chamados/{protocolo}/conversa/digitando")
    def tecnico_digitando(protocolo: str, s: SessaoConta = Depends(tecnico_logado)):
        if msgs.ativa(protocolo):
            msgs.avisar_digitando(protocolo, "tecnico")
        return {"ok": True}

    @app.post("/tecnico/chamados/{protocolo}/conversa/encerrar")
    def encerrar_conversa(protocolo: str, s: SessaoConta = Depends(tecnico_logado)):
        msgs.encerrar(protocolo, contas.nome(s.email))
        return estado_conversa(chamado(protocolo), 0)

    @app.post("/tecnico/distribuir")
    def distribuir(s: SessaoConta = Depends(tecnico_logado)):
        try:
            return {"distribuidos": motor.registro.distribuir([t["email"] for t in contas.equipe()], s.email)}
        except ArquivoEmUso as e:
            raise HTTPException(409, str(e))

    @app.patch("/tecnico/chamados/{protocolo}")
    def atualizar_chamado(protocolo: str, a: AtualizacaoChamado, s: SessaoConta = Depends(tecnico_logado)):
        if a.tecnico and a.tecnico not in {t["email"] for t in contas.equipe()}:
            raise HTTPException(422, "Esse técnico não faz parte da equipe.")
        try:
            return publico(motor.registro.atualizar(protocolo, a.status, a.tecnico, a.observacao, por=s.email))
        except KeyError:
            raise HTTPException(404, f"Chamado {protocolo} não encontrado.")
        except ValueError as e:
            raise HTTPException(422, str(e))
        except ArquivoEmUso as e:
            raise HTTPException(409, str(e))


    def admin_logado(s: SessaoConta = Depends(tecnico_logado)) -> SessaoConta:
        if contas.perfil(s.email).get("papel") != "admin":
            raise HTTPException(403, "Só administradores podem acessar esta área.")
        return s

    def contas_do_tipo(tipo: str) -> Contas:
        if tipo not in ("tecnico", "colaborador"):
            raise HTTPException(422, "Tipo de conta inválido.")
        return contas if tipo == "tecnico" else contas_colab

    @app.get("/tecnico/admin/indicadores")
    def ver_indicadores(dias: int = 14, s: SessaoConta = Depends(admin_logado)):
        try:
            chamados = motor.registro.listar()
        except ArquivoEmUso as e:
            raise HTTPException(409, str(e))
        nomes = {t["email"]: t["nome"] for t in contas.equipe()}
        return indicadores(motor.atendimentos.listar(), chamados, ler_avaliacoes(cfg.avaliacoes), nomes,
                           dias=max(7, min(dias, 60)))

    @app.get("/tecnico/admin/contas")
    def listar_contas(s: SessaoConta = Depends(admin_logado)):
        return {"tecnicos": contas.listar_detalhes(), "colaboradores": contas_colab.listar_detalhes()}

    @app.post("/tecnico/admin/contas")
    def criar_conta(n: NovaConta, s: SessaoConta = Depends(admin_logado)):
        papel = ("admin" if n.admin else "tecnico") if n.tipo == "tecnico" else "colaborador"
        try:
            senha = contas_do_tipo(n.tipo).adicionar(n.email, n.nome, papel)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"email": n.email.strip().lower(), "senha_provisoria": senha}

    @app.post("/tecnico/admin/contas/redefinir")
    def redefinir_conta(a: AcaoConta, s: SessaoConta = Depends(admin_logado)):
        if a.tipo == "tecnico" and a.email.strip().lower() == s.email:
            raise HTTPException(422, "Para trocar a sua própria senha, use Minha conta.")
        try:
            senha = contas_do_tipo(a.tipo).redefinir(a.email)
        except KeyError:
            raise HTTPException(404, "Conta não encontrada.")
        return {"email": a.email.strip().lower(), "senha_provisoria": senha}

    @app.post("/tecnico/admin/contas/ativo")
    def ativar_conta(a: AcaoConta, s: SessaoConta = Depends(admin_logado)):
        if a.tipo == "tecnico" and a.email.strip().lower() == s.email:
            raise HTTPException(422, "Você não pode desativar a sua própria conta.")
        try:
            contas_do_tipo(a.tipo).definir_ativo(a.email, a.ativo)
        except KeyError:
            raise HTTPException(404, "Conta não encontrada.")
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok", "diretorio": cfg.diretorio_modo, "planilha": str(cfg.planilha),
                "planilha_existe": cfg.planilha.exists()}

    app.mount("/arquivos/inicio", StaticFiles(directory=PAGINA_INICIO), name="inicio")
    app.mount("/arquivos/chat", StaticFiles(directory=PAGINA_CHAT), name="chat")
    app.mount("/arquivos/painel", StaticFiles(directory=PAGINA_PAINEL), name="painel")
    app.mount("/arquivos/visual", StaticFiles(directory=VISUAL), name="visual")
    return app


def _app_do_ambiente() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    return criar_app(Config.do_ambiente())


app = _app_do_ambiente
