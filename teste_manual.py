import socket
import json
import threading
import time

BROKERS = {
    "setor_a": ("localhost", 7001),
    "setor_b": ("localhost", 7002),
    "setor_c": ("localhost", 7003),
}

def enviar(setor, ocorrencia, prioridade, delay):
    time.sleep(delay)

    try:
        host, porta = BROKERS[setor]

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            sock.connect((host, porta))
        except:
            print(f"[ERRO] broker {setor} offline")
            return

        payload = {
            "ocorrencia": ocorrencia,
            "prioridade": prioridade
        }

        sock.sendall(json.dumps(payload).encode())

        print(f"[ENVIADA] {ocorrencia} prioridade={prioridade}")

        sock.close()

    except Exception as e:
        print("Erro:", e)

threading.Thread(
    target=enviar,
    args=("setor_a", "averiguacao", 1, 0)
).start()

threading.Thread(
    target=enviar,
    args=("setor_b", "possivel_ataque", 2, 0.1)
).start()

threading.Thread(
    target=enviar,
    args=("setor_c", "ataque_concreto", 3, 0.2)
).start()

threading.Thread(
    target=enviar,
    args=("setor_a", "possível_ataque", 2, 0.3)
).start()

threading.Thread(
    target=enviar,
    args=("setor_b", "averiguacao", 1, 0.4)
).start()