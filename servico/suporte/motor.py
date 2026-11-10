import threading

from .atendimento import Atendimento
from .base_conhecimento import BaseConhecimento
from .classificador import Classificador, Regras
from .colaboradores import Colaboradores
from .config import Config
from .contas import Contas, ContasTecnicos
from .diretorio import Diretorio, criar_diretorio
from .estatisticas import Atendimentos
from .mensagens import Mensagens
from .planilha import Planilha
from .registro import RegistroChamados
from .texto import Analisador


class PlanilhaIndisponivel(Exception):
    pass


class Motor:
    def __init__(self, cfg: Config, diretorio: Diretorio | None = None):
        self.cfg = cfg
        self.analisador = Analisador(cfg.sinonimos)
        self.regras = Regras(cfg.regras)
        self.kb = BaseConhecimento(cfg.base_conhecimento, self.analisador)
        self.diretorio = diretorio or criar_diretorio(cfg)
        self.contas = ContasTecnicos(cfg.tecnicos)
        self.contas_colaboradores = Contas(cfg.contas_colaboradores)
        self.mensagens = Mensagens(cfg.mensagens)
        self.colaboradores = Colaboradores(cfg.colaboradores)
        self.atendimentos = Atendimentos(cfg.atendimentos)
        self.registro = RegistroChamados(cfg.encaminhados, self.regras.minutos_por_urgencia,
                                         self.regras.minutos_por_chamado_na_frente)
        self._planilha = Planilha(cfg.planilha)
        self._linhas = None
        self._atendimento: Atendimento | None = None
        self._trava = threading.Lock()

    def atendimento(self) -> Atendimento:
        try:
            linhas = self._planilha.linhas()
        except FileNotFoundError:
            raise PlanilhaIndisponivel(f"Planilha não encontrada: {self.cfg.planilha}")
        except ValueError as e:
            raise PlanilhaIndisponivel(str(e))
        with self._trava:
            if self._atendimento is None or self._linhas is not linhas:
                classificador = Classificador(linhas, self.kb.artigos, self.analisador, self.regras)
                self._atendimento = Atendimento(classificador, self.kb, self.diretorio, self.regras)
                self._linhas = linhas
            return self._atendimento
