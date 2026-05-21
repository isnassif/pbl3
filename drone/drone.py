import socket
import json
import sys
import time
import os
import sys

sys.stdout.reconfigure(line_buffering=True)
def _parse_addr(env_key, default_host, default_port):
    val = os.getenv(env_key)
    if val:
        host, port = val.rsplit(":", 1)
        return (host, int(port))
    return (default_host, default_port)

#BROKERS = [
#    _parse_addr("BROKER_A", "broker_a", 6001),
#    _parse_addr("BROKER_B", "broker_b", 6002),
#    _parse_addr("BROKER_C", "broker_c", 6003),
#]

BROKERS = [
    _parse_addr("BROKER_A", "127.0.0.1", 6001),
    _parse_addr("BROKER_B", "127.0.0.1", 6002),
    _parse_addr("BROKER_C", "127.0.0.1", 6003),
]


def conectar():
    while True:
        for host, porta in BROKERS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, porta))

                # timeout para não travar no recv
                sock.settimeout(1)

                print(f"Conectado ao broker na porta {porta}")
                return sock

            except:
                continue

        print("Nenhum broker disponível, tentando novamente...")
        time.sleep(1)


if len(sys.argv) < 2:
    print("Uso: python drone.py <drone_id>")
    exit(1)

drone_id = sys.argv[1]


try:
    while True:

        sock = conectar()

        cadastro = {
            "type": "CADASTRO",
            "drone_id": drone_id
        }

        sock.sendall(json.dumps(cadastro).encode())

        print(f"Drone {drone_id} registrado no broker")

        try:
            while True:

                try:
                    data = sock.recv(1024)

                    if not data:
                        raise Exception("conexão caiu")

                    msg = json.loads(data.decode())

                    if msg["type"] == "DISPATCH":

                        print(
                            f"Drone {drone_id} atendendo ocorrência:"
                            f" {msg['ocorrencia']}"
                        )

                        time.sleep(10)

                        concluido = {
                            "type": "CONCLUIDO"
                        }

                        sock.sendall(json.dumps(concluido).encode())

                except socket.timeout:
                    # normal — apenas continua esperando
                    continue

        except:
            print(f"Drone {drone_id} perdeu conexão, tentando reconectar...")
            sock.close()
            time.sleep(1)

except KeyboardInterrupt:
    print(f"\nDrone {drone_id} encerrado.")