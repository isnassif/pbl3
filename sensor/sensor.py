import socket
import random
import time
import json
import sys
import os

SERVIDOR_HOST = os.getenv("SERVIDOR_HOST", "localhost")

BROKERS_SENSORES = {
    "setor_a": ("broker_a", 7001),
    "setor_b": ("broker_b", 7002),
    "setor_c": ("broker_c", 7003),
}

if len(sys.argv) < 2:
    print("Uso: python sensor.py <setor_a|setor_b|setor_c>")
    sys.exit(1)

meu_setor = sys.argv[1]

while True:
    try:
        host, port = BROKERS_SENSORES[meu_setor]
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.connect((host, port))

        prioridade = random.randint(1, 3)

        tipos_ocorrencia = {
            1: "averiguacao",
            2: "possivel_ataque",
            3: "ataque_concreto"
        }

        payload = json.dumps({
            "ocorrencia": tipos_ocorrencia[prioridade],
            "prioridade": prioridade,
            "origem": meu_setor
        })
        print(f"OCORRÊNCIA: {tipos_ocorrencia[prioridade]}\nPRIORIDADE{prioridade}")
        tcp_socket.sendall(payload.encode())
        tcp_socket.close()

    except Exception as e:
        print(f"Erro de conexão: {e}")

    time.sleep(8)