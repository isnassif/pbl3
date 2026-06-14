"""
TESTE 1 — CARGA E ORDENAÇÃO
Envia N requisições em ordem aleatória para brokers aleatórios
e imprime o resultado esperado da fila ordenada para comparação visual.

Uso:
    python teste_carga.py <quantidade>
    python teste_carga.py 10
"""

import socket
import json
import threading
import time
import random
import sys

BROKERS_SENSORES = {
    "setor_a": ("127.0.0.1", 7001),
    "setor_b": ("127.0.0.1", 7002),
    "setor_c": ("127.0.0.1", 7003),
}

TIPOS = {
    1: "averiguacao",
    2: "possivel_ataque",
    3: "ataque_concreto"
}

PRIORIDADE_LABEL = {1: "BAIXA", 2: "MÉDIA", 3: "ALTA"}


def enviar(setor, ocorrencia, prioridade, indice, delay):
    time.sleep(delay)
    try:
        host, porta = BROKERS_SENSORES[setor]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, porta))
        payload = json.dumps({
            "ocorrencia": ocorrencia,
            "prioridade": prioridade,
            "origem": setor
        })
        sock.sendall(payload.encode())
        sock.close()
        print(f"  [{indice:>3}] ✓  {setor:<8}  {ocorrencia:<20}  P{prioridade} {PRIORIDADE_LABEL[prioridade]}")
    except Exception as e:
        print(f"  [{indice:>3}] ✗  {setor:<8}  ERRO: {e}")


def main():
    if len(sys.argv) < 2:
        try:
            quantidade = int(input("Quantas requisições enviar? "))
        except ValueError:
            print("Valor inválido.")
            sys.exit(1)
    else:
        quantidade = int(sys.argv[1])

    setores = list(BROKERS_SENSORES.keys())
    requisicoes = []
    for i in range(quantidade):
        prioridade = random.randint(1, 3)
        setor = random.choice(setores)
        requisicoes.append((setor, TIPOS[prioridade], prioridade))

    print()
    print("=" * 60)
    print(f"  TESTE DE CARGA — {quantidade} requisições desordenadas")
    print("=" * 60)
    print(f"  {'#':>3}    {'SETOR':<8}  {'OCORRÊNCIA':<20}  PRIORIDADE")
    print("-" * 60)

    threads = []
    for i, (setor, ocorrencia, prioridade) in enumerate(requisicoes):
        delay = random.uniform(0, 1.5)
        t = threading.Thread(
            target=enviar,
            args=(setor, ocorrencia, prioridade, i + 1, delay)
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print()
    print("=" * 60)
    print("  ORDEM ESPERADA NA FILA (do broker):")
    print("=" * 60)
    print(f"  {'#':>3}  {'OCORRÊNCIA':<20}  {'PRIOR.':<10}  ORIGEM")
    print("-" * 60)

    ordenadas = sorted(requisicoes, key=lambda r: (-r[2], r[0]))
    for i, (setor, ocorrencia, prioridade) in enumerate(ordenadas, start=1):
        print(f"  {i:>3}  {ocorrencia:<20}  P{prioridade} {PRIORIDADE_LABEL[prioridade]:<6}  {setor}")

    print()
    print("  Compare com a fila exibida nos brokers para verificar consistência.")
    print("=" * 60)


if __name__ == "__main__":
    main()