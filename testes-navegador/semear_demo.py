import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servico"))
from suporte.config import Config
from suporte.conversa import Conversa
from suporte.motor import Motor

PROBLEMAS = ["a vpn não conecta de casa", "a impressora não imprime", "o computador está muito lento",
             "o Outlook não envia nem recebe e-mails", "o headset está sem áudio", "minha caixa de e-mail está cheia",
             "o Wi-Fi fica caindo toda hora", "preciso instalar um programa", "acabou o toner da impressora",
             "o monitor não liga"]
NAO_ENTENDIDAS = ["deu ruim no portal", "o negócio lá não vai", "deu ruim no portal"]
EMAILS = ["xxxxx2@teste.com", "xxxxx3@teste.com", "xxxxx4@teste.com"]
PESOS_DIAS = [3, 4, 5, 4, 3, 1, 1, 4, 5, 6, 5, 4, 2, 2]


def main() -> None:
    random.seed(7)
    cfg = Config.do_ambiente()
    motor = Motor(cfg)
    conversa = Conversa(motor)
    for _ in range(42):
        s = conversa.sessao_da_conta(None, random.choice(EMAILS), "Demo")
        conversa.responder(s, random.choice(PROBLEMAS))
        sorte = random.random()
        if sorte < 0.62:
            conversa.responder(s, "resolveu")
            if s.a_avaliar and random.random() < 0.8:
                conversa.avaliar(s, random.choices([5, 4, 3, 2, 1], [46, 30, 12, 7, 5])[0])
        elif sorte < 0.9:
            conversa.responder(s, "não resolveu")
    for frase in NAO_ENTENDIDAS:
        conversa.responder(conversa.sessao_da_conta(None, "xxxxx2@teste.com", "Demo"), frase)

    agora = datetime.now()
    with cfg.atendimentos.open(encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    dia = {}
    for linha in linhas:
        chave = linha["protocolo"] or linha["texto"]
        dia.setdefault(chave, random.choices(range(14), PESOS_DIAS)[0])
        linha["data"] = f"{agora - timedelta(days=dia[chave], hours=random.randint(1, 6)):%d/%m/%Y %H:%M}"
    with cfg.atendimentos.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)

    equipe = [t["email"] for t in motor.contas.equipe()]
    for i, c in enumerate(motor.registro.listar()):
        if i % 3 == 0:
            motor.registro.atualizar(c["protocolo"], status="Concluído", tecnico=equipe[i % len(equipe)], por=equipe[0])
        elif i % 3 == 1:
            motor.registro.atualizar(c["protocolo"], status="Em atendimento", tecnico=equipe[i % len(equipe)], por=equipe[0])


if __name__ == "__main__":
    main()
