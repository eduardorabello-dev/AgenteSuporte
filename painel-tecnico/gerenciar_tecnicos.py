import argparse
import io
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "servico"))
from suporte.config import PASTA_PAINEL
from suporte.contas import ContasTecnicos


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Contas do painel do técnico")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("listar")
    a = sub.add_parser("adicionar")
    a.add_argument("email")
    a.add_argument("nome")
    a.add_argument("--admin", action="store_true")
    r = sub.add_parser("redefinir")
    r.add_argument("email")
    args = p.parse_args()

    contas = ContasTecnicos(Path(os.environ.get("TECNICOS", PASTA_PAINEL / "tecnicos.json")))
    try:
        if args.comando == "listar":
            for t in contas.equipe():
                print(f"{t['email']:<35} {t['nome']:<15} {t['papel']}")
        elif args.comando == "adicionar":
            senha = contas.adicionar(args.email, args.nome, "admin" if args.admin else "tecnico")
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
