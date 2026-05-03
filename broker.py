from RicartAgrawala import RicartAgrawala
import socket
import threading
import json
import sys
import time
import random




BROKERS = {
    "setor_a": ("localhost", 5001),
    "setor_b": ("localhost", 5002),
    "setor_c": ("localhost", 5003),
}

PORTAS_DRONES = {
    "setor_a": 6001,
    "setor_b": 6002,
    "setor_c": 6003,
}



class Broker:
    def __init__(self, meu_id):
        self.lock_drones = threading.Lock()
        self.drones = {}
        self.fila =[]
        self.meu_id = meu_id
        self.ra = RicartAgrawala(meu_id, BROKERS, self)

    def broadcast_update(self,drone_id,status,owner,in_use_by):
        msg = {
            "type": "DRONE_UPDATE",
            "drone_id": drone_id,
            "status": status,
            "owner": owner,
            "in_use_by": in_use_by
        }    
        for broker_id, endereco in BROKERS.items():
            if broker_id == self.meu_id:
                continue

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(endereco)
                sock.sendall(json.dumps(msg).encode())
                sock.close()
            except:
                pass

    def requisitarDrone(self,ocorrencia):
        self.ra.pedirPermissao()
        with self.lock_drones:
            for drone_id, info in self.drones.items():
                if info["status"] == 0: # se estiver livre
                    info["status"] = 1
                    info["in_use_by"] = self.meu_id
                    conn = self.drones[drone_id]["conn"]
                    self.broadcast_update(drone_id,1,info["owner"],self.meu_id)
                    dispatch = {"type": "DISPATCH", "ocorrencia": ocorrencia}
                    if conn is not None:
                        conn.sendall(json.dumps(dispatch).encode())
                        print(f"drone{drone_id} foi reservado LOCAL")
                    else:
                        # 🔥 manda pro broker dono
                        dono = info["owner"]

                        msg = {
                            "type": "EXECUTE",
                            "drone_id": drone_id,
                            "ocorrencia": ocorrencia
                        }

                        endereco = BROKERS[dono]

                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.connect(endereco)
                        sock.sendall(json.dumps(msg).encode())
                        sock.close()

                        print(f"drone{drone_id} foi reservado REMOTO via {dono}")
                    break
            else:
                self.fila.append(ocorrencia)
                    
        self.ra.liberarRecurso()
    

    def droneConnect(self,port):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', port))
        server.listen(5)
        print(f"Servidor TCP aguardando ventiladores na porta {port}...")
        while True:
            client_socket, addr = server.accept()
            mensagem = client_socket.recv(1024)
            drone = json.loads(mensagem.decode())
            if drone["type"] == "CADASTRO":
                drone_id = drone["drone_id"]
                with self.lock_drones:
                    self.drones[drone_id] = {
                        "status": 0,
                        "owner": self.meu_id,
                        "in_use_by": None,
                        "conn": client_socket
                    }
                self.broadcast_update(
                    drone_id,
                    0,
                    self.meu_id,   # 🔥 esse broker é o dono
                    None
                )
                time.sleep(0.5) 
                threading.Thread(
                    target=self._loopDrone,
                    args=(drone_id, client_socket),
                    daemon=True
                ).start()

    
    

    def _loopDrone(self,drone_id, client_socket):
        while True:
            try:
                data = client_socket.recv(1024)
                if not data:
                    break
                drone = json.loads(data.decode())
                if drone["type"] == "CONCLUIDO":
                    with self.lock_drones:
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None
                    self.broadcast_update(drone_id,0,self.drones[drone_id]["owner"],None)
                    self._processarfila()
            except:
                break
    

    def _processarfila(self):
            if len(self.fila) == 0:
                return
            ocorrencia = self.fila.pop(0)
            self.requisitarDrone(ocorrencia)



    def iniciar(self):
        threading.Thread(
            target=self.droneConnect,
            args=(PORTAS_DRONES[self.meu_id],),
            daemon=True
        ).start()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python broker.py <setor_a|setor_b|setor_c>")
        sys.exit(1)

    meu_id = sys.argv[1]
    broker = Broker(meu_id)
    broker.iniciar()

    while True:
        ocorrencia = input(f"[{meu_id}] Digite ocorrência: ")
        broker.requisitarDrone(ocorrencia)