import io
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "servico"))
from suporte.config import Config
from suporte.conversa import Conversa
from suporte.motor import Motor


def carregar_env() -> None:
    import os

    arquivo = RAIZ / ".env"
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*(.*)$", linha):
                os.environ.setdefault(m.group(1), m.group(2).strip())


def para_terminal(texto: str) -> str:
    return texto.replace("**", "")


def main() -> None:
    for fluxo in (sys.stdout, sys.stdin):
        if isinstance(fluxo, io.TextIOWrapper):
            fluxo.reconfigure(encoding="utf-8")
    carregar_env()
    conversa = Conversa(Motor(Config.do_ambiente()))
    sessao = conversa.sessao(None)

    print("=" * 70)
    print(para_terminal(conversa.boas_vindas()["texto"]))
    print("\n(Para sair, digite 'sair'.)")
    print("=" * 70)
    while True:
        try:
            mensagem = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if mensagem.lower() in {"sair", "exit", "quit", "tchau"}:
            print("\nSuporte: Até mais!")
            break
        if not mensagem:
            continue
        r = conversa.responder(sessao, mensagem)
        print("\nSuporte: " + para_terminal(r["texto"]).replace("\n", "\n         "))


if __name__ == "__main__":
    main()
