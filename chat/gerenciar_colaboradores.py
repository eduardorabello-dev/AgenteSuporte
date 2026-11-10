import argparse
import io
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "servico"))
from suporte.config import PASTA_CHAT
from suporte.contas import Contas


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Contas de login do chat (colaboradores)")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("listar")
    a = sub.add_parser("adicionar")
    a.add_argument("email")
    a.add_argument("nome")
    r = sub.add_parser("redefinir")
    r.add_argument("email")
    args = p.parse_args()

    contas = Contas(Path(os.environ.get("CONTAS_COLABORADORES", PASTA_CHAT / "contas-colaboradores.json")))
    try:
        if args.comando == "listar":
            for c in contas.equipe():
                print(f"{c['email']:<35} {c['nome']}")
        elif args.comando == "adicionar":
            senha = contas.adicionar(args.email, args.nome, "colaborador")
            print(f"Conta criada: {args.email.lower()}\nSenha provisória: {senha}")
        else:
            senha = contas.redefinir(args.email)
            print(f"Nova senha provisória de {args.email.lower()}: {senha}")
            print("Quem estava logado com a senha antiga é desconectado.")
    except (ValueError, KeyError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
