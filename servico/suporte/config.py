import os
from dataclasses import dataclass
from pathlib import Path

SERVICO = Path(__file__).resolve().parent.parent
RAIZ_PROJETO = SERVICO.parent
CONHECIMENTO = SERVICO / "conhecimento"
VISUAL = SERVICO / "visual"
PAGINA_INICIO = RAIZ_PROJETO / "inicio" / "pagina"
PASTA_CHAT = RAIZ_PROJETO / "chat"
PAGINA_CHAT = PASTA_CHAT / "pagina"
PASTA_PAINEL = RAIZ_PROJETO / "painel-tecnico"
PAGINA_PAINEL = PASTA_PAINEL / "pagina"
REGISTROS = RAIZ_PROJETO / "registros"


@dataclass(frozen=True)
class Config:
    planilha: Path
    base_conhecimento: Path
    sinonimos: Path
    regras: Path
    usuarios_mock: Path
    encaminhados: Path
    diretorio_modo: str
    politica_expiracao_dias: int
    ad_servidor: str
    ad_usuario: str
    ad_senha: str
    ad_base_dn: str
    ad_ssl: bool
    avaliacoes: Path = REGISTROS / "avaliacoes.csv"
    tecnicos: Path = PASTA_PAINEL / "tecnicos.json"
    mensagens: Path = REGISTROS / "mensagens-tecnico.csv"
    colaboradores: Path = REGISTROS / "colaboradores.csv"
    contas_colaboradores: Path = PASTA_CHAT / "contas-colaboradores.json"
    atendimentos: Path = REGISTROS / "atendimentos.csv"

    @classmethod
    def do_ambiente(cls) -> "Config":
        return cls(
            planilha=Path(os.environ.get("PLANILHA_CHAMADOS", CONHECIMENTO / "chamados-rotulados.xlsx")),
            base_conhecimento=Path(os.environ.get("BASE_CONHECIMENTO", CONHECIMENTO / "base-conhecimento.json")),
            sinonimos=Path(os.environ.get("SINONIMOS", CONHECIMENTO / "sinonimos.json")),
            regras=Path(os.environ.get("REGRAS", CONHECIMENTO / "regras.json")),
            usuarios_mock=Path(os.environ.get("USUARIOS_MOCK", CONHECIMENTO / "usuarios-mock.json")),
            encaminhados=Path(os.environ.get("CHAMADOS_ENCAMINHADOS", REGISTROS / "chamados-encaminhados.csv")),
            diretorio_modo=os.environ.get("DIRETORIO_MODO", "mock").lower(),
            politica_expiracao_dias=int(os.environ.get("POLITICA_EXPIRACAO_DIAS", "90")),
            ad_servidor=os.environ.get("AD_SERVIDOR", ""),
            ad_usuario=os.environ.get("AD_USUARIO", ""),
            ad_senha=os.environ.get("AD_SENHA", ""),
            ad_base_dn=os.environ.get("AD_BASE_DN", ""),
            ad_ssl=os.environ.get("AD_SSL", "true").lower() == "true",
            avaliacoes=Path(os.environ.get("AVALIACOES", REGISTROS / "avaliacoes.csv")),
            tecnicos=Path(os.environ.get("TECNICOS", PASTA_PAINEL / "tecnicos.json")),
            mensagens=Path(os.environ.get("MENSAGENS_TECNICO", REGISTROS / "mensagens-tecnico.csv")),
            colaboradores=Path(os.environ.get("COLABORADORES", REGISTROS / "colaboradores.csv")),
            contas_colaboradores=Path(os.environ.get("CONTAS_COLABORADORES", PASTA_CHAT / "contas-colaboradores.json")),
            atendimentos=Path(os.environ.get("ATENDIMENTOS", REGISTROS / "atendimentos.csv")),
        )
