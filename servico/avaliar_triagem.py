import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "servico"))
from suporte.classificador import Classificador, Regras
from suporte.config import CONHECIMENTO
from suporte.planilha import Planilha
from suporte.texto import Analisador


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--planilha", type=Path,
                      default=Path(os.environ.get("PLANILHA_CHAMADOS", CONHECIMENTO / "chamados-rotulados.xlsx")))
    args.add_argument("--saida", type=Path, help="grava o resultado detalhado neste CSV (abre no Excel)")
    opcoes = args.parse_args()

    base = Planilha(opcoes.planilha).linhas()
    artigos = json.loads((CONHECIMENTO / "base-conhecimento.json").read_text(encoding="utf-8"))
    clf = Classificador(base, artigos, Analisador(CONHECIMENTO / "sinonimos.json"), Regras(CONHECIMENTO / "regras.json"))

    resultados = []
    for linha in base:
        r = clf.classificar(linha.descricao)
        res = {
            "id": linha.id, "descricao": linha.descricao,
            "categoria_esperada": linha.categoria, "categoria_obtida": r["categoria"],
            "categoria_ok": r["categoria"] == linha.categoria,
            "urgencia_esperada": linha.urgencia, "urgencia_obtida": r["urgencia"],
            "urgencia_ok": r["urgencia"] == linha.urgencia,
        }
        resultados.append(res)
        marca = "OK" if res["categoria_ok"] and res["urgencia_ok"] else " x"
        print(f"[{marca}] #{linha.id:<3} {r['categoria']:<20} {r['urgencia']:<8} | "
              f"esperado {linha.categoria} / {linha.urgencia}")

    n = len(resultados)
    cat = sum(r["categoria_ok"] for r in resultados)
    urg = sum(r["urgencia_ok"] for r in resultados)
    ambos = sum(r["categoria_ok"] and r["urgencia_ok"] for r in resultados)
    print(f"\nCategoria: {cat}/{n} ({cat / n:.0%})")
    print(f"Urgência:  {urg}/{n} ({urg / n:.0%})")
    print(f"Ambos:     {ambos}/{n} ({ambos / n:.0%})")

    confusoes = Counter(f"{r['categoria_esperada']} -> {r['categoria_obtida']}"
                        for r in resultados if not r["categoria_ok"])
    if confusoes:
        print("\nCategoria errada (esperado -> obtido):")
        for par, qtd in confusoes.most_common():
            print(f"  {par:<45} {qtd}x")

    if opcoes.saida:
        with opcoes.saida.open("w", newline="", encoding="utf-8-sig") as f:
            escritor = csv.DictWriter(f, fieldnames=list(resultados[0]), delimiter=";")
            escritor.writeheader()
            escritor.writerows(resultados)
        print(f"\nDetalhes em {opcoes.saida}")


if __name__ == "__main__":
    main()
