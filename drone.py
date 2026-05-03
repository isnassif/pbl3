import socket
import json
import sys
import time

if len(sys.argv) < 3:
    print("Uso: python drone.py <drone_id> <porta_broker>")
    exit(1)

drone_id = sys.argv[1]
porta = int(sys.argv[2])

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("localhost", porta))

# envia cadastro
cadastro = {
    "type": "CADASTRO",
    "drone_id": drone_id
}
sock.sendall(json.dumps(cadastro).encode())

print(f"Drone {drone_id} conectado ao broker na porta {porta}")

while True:
    data = sock.recv(1024)
    if not data:
        break

    msg = json.loads(data.decode())

    if msg["type"] == "DISPATCH":
        print(f"Drone {drone_id} atendendo ocorrência:", msg["ocorrencia"])
        
        # simula trabalho
        time.sleep(3)

        # avisa que terminou
        concluido = {
            "type": "CONCLUIDO"
        }
        sock.sendall(json.dumps(concluido).encode())