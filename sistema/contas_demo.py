import io
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "servico"))
from suporte.config import PASTA_CHAT, PASTA_PAINEL
from suporte.contas import Contas

TECNICOS = [("admin.xxxxx7@teste.com", "XXXXX", "admin"), ("admin.xxxxx8@teste.com", "XXXXX", "admin")]
COLABORADORES = [("xxxxx1@teste.com", "XXXXX"), ("xxxxx2@teste.com", "XXXXX"),
                 ("xxxxx3@teste.com", "XXXXX"), ("xxxxx4@teste.com", "XXXXX")]


def criar() -> dict[str, str]:
    tecnicos = Contas(Path(os.environ.get("TECNICOS", PASTA_PAINEL / "tecnicos.json")))
    colaboradores = Contas(Path(os.environ.get("CONTAS_COLABORADORES", PASTA_CHAT / "contas-colaboradores.json")))
    existentes = {c["email"] for c in tecnicos.listar_detalhes() + colaboradores.listar_detalhes()}
    senhas: dict[str, str] = {}
    for email, nome, papel in TECNICOS:
        if email not in existentes:
            senhas[email] = tecnicos.adicionar(email, nome, papel)
    for email, nome in COLABORADORES:
        if email not in existentes:
            senhas[email] = colaboradores.adicionar(email, nome, "colaborador")
    return senhas


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    senhas = criar()
    if "--json" in sys.argv:
        print(json.dumps(senhas))
    elif senhas:
        print("Contas de demonstração criadas (anote: as senhas provisórias aparecem só agora):")
        for email, senha in senhas.items():
            print(f"  {email:<28} {senha}")
    else:
        print("As contas de demonstração já existem (nada foi alterado).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
