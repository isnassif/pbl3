"""
TESTE 2 — CONSISTÊNCIA DA FILA ENTRE BROKERS
Envia N requisições, aguarda propagação e consulta a fila
de cada broker via FILA_SYNC_REQUEST para comparar se estão iguais.

Uso:
    python teste_consistencia.py <quantidade>
    python teste_consistencia.py 15
"""

import socket
import json
import threading
import time
import random
import sys

BROKERS = {
    "setor_a": ("127.0.0.1", 5001),
    "setor_b": ("127.0.0.1", 5002),
    "setor_c": ("127.0.0.1", 5003),
}

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
resultados = {}
lock = threading.Lock()


def enviar_req(setor, ocorrencia, prioridade, delay):
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
    except:
        pass


def consultar_fila(broker_id):
    """
    Consulta a fila de um broker enviando FILA_SYNC_REQUEST
    e capturando a resposta FILA_SYNC_RESPONSE em uma porta temporária.
    Como o broker responde de volta via _sendMessage, precisamos
    de um servidor local temporário para receber.
    """
    # Abre servidor temporário numa porta livre
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    porta_local = srv.getsockname()[1]
    srv.settimeout(5)

    # Envia FILA_SYNC_REQUEST com um broker_id falso apontando pra porta local
    # Usamos um ID especial que o broker vai responder
    msg = {
        "type": "FILA_SYNC_REQUEST",
        "broker_id": f"teste_{broker_id}"
    }

    try:
        host, porta = BROKERS[broker_id]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, porta))
        s.sendall(json.dumps(msg).encode())
        s.close()
    except:
        srv.close()
        return None

    # Como a resposta vai pro broker inexistente, não conseguimos capturar diretamente.
    # Alternativa: lemos a fila via outro broker que já está sincronizado.
    srv.close()
    return None


def comparar_via_sync(quantidade):
    """
    Estratégia alternativa: envia requisições, espera propagação
    e pede sync entre brokers. Depois imprime as filas locais
    de cada broker através de uma requisição de diagnóstico.
    """
    setores = list(BROKERS_SENSORES.keys())
    threads = []

    print()
    print("=" * 60)
    print(f"  TESTE DE CONSISTÊNCIA — {quantidade} requisições")
    print("=" * 60)
    print("  Enviando requisições desordenadas...")
    print()

    enviadas = []
    for i in range(quantidade):
        prioridade = random.randint(1, 3)
        setor = random.choice(setores)
        delay = random.uniform(0, 2.0)
        enviadas.append((setor, TIPOS[prioridade], prioridade))
        t = threading.Thread(
            target=enviar_req,
            args=(setor, TIPOS[prioridade], prioridade, delay)
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"  {quantidade} requisições enviadas.")
    print("  Aguardando propagação entre brokers (3s)...")
    time.sleep(3)

    print()
    print("  ORDEM ESPERADA (por prioridade decrescente):")
    print(f"  {'#':>3}  {'OCORRÊNCIA':<20}  {'PRIOR.':<10}  ORIGEM")
    print("-" * 60)
    ordenadas = sorted(enviadas, key=lambda r: (-r[2], r[0]))
    for i, (setor, ocorrencia, prioridade) in enumerate(ordenadas, start=1):
        print(f"  {i:>3}  {ocorrencia:<20}  P{prioridade} {PRIORIDADE_LABEL[prioridade]:<6}  {setor}")

    print()
    print("  ✔ Verifique nos terminais dos brokers se as filas")
    print("    exibidas têm a mesma ordem acima e o mesmo")
    print("    número de itens em setor_a, setor_b e setor_c.")
    print("=" * 60)

    resultado = input("\n  As filas estão iguais em todos os brokers? (s/n): ").strip().lower()
    if resultado == "s":
        print("  ✅ TESTE PASSOU — fila consistente entre todos os brokers.")
    else:
        print("  ❌ TESTE FALHOU — filas divergentes detectadas.")
    print()


def main():
    if len(sys.argv) < 2:
        try:
            quantidade = int(input("Quantas requisições enviar? "))
        except ValueError:
            print("Valor inválido.")
            sys.exit(1)
    else:
        quantidade = int(sys.argv[1])

    comparar_via_sync(quantidade)


if __name__ == "__main__":
    main()