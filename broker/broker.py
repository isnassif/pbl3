from RicartAgrawala import RicartAgrawala
import socket
import threading
import json
import sys
import time
import uuid

BROKERS = {
    "setor_a": ("broker_a", 5001),
    "setor_b": ("broker_b", 5002),
    "setor_c": ("broker_c", 5003),
}

PORTAS_DRONES = {
    "setor_a": 6001,
    "setor_b": 6002,
    "setor_c": 6003,
}

PORTAS_SENSORES = {
    "setor_a": 7001,
    "setor_b": 7002,
    "setor_c": 7003,
}


class Broker:
    def __init__(self, meu_id):
        self.processando_fila = False
        self.lock_processamento = threading.Lock()
        self.lock_secao = threading.Lock()
        self.meu_id = meu_id
        self.lock_drones = threading.Lock()
        self.lock_fila = threading.Lock()
        self.drones = {}
        self.fila = []
        self.ra = RicartAgrawala(meu_id, BROKERS, self)

    def mostrarFila(self, evento="ATUALIZAÇÃO"):
        print("\n")
        print("=" * 60)
        print(f"[{self.meu_id}] FILA COMPARTILHADA -> {evento}")
        print("=" * 60)

        if not self.fila:
            print("FILA VAZIA")
        else:
            for i, r in enumerate(self.fila, start=1):
                print(
                    f"{i}. "
                    f"{r['ocorrencia']} | "
                    f"P{r['prioridade']} | "
                    f"{r['origem']}"
                )

        print("=" * 60)

    # ─── BROADCAST HELPERS ────────────────────────────────────────────────────

    def broadcast_update(self, drone_id, status, owner, in_use_by):
        """Avisa todos os outros brokers sobre mudança de estado de um drone."""
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
                sock.settimeout(2)
                sock.connect(endereco)
                sock.sendall(json.dumps(msg).encode())
                sock.close()
            except:
                pass

    def _broadcast_fila(self, req_id, ocorrencia, prioridade, timestamp):
        """Sincroniza a fila de requisições com os outros brokers."""
        msg = {
            "type": "FILA_REQUISICAO",
            "req_id": req_id,
            "ocorrencia": ocorrencia,
            "origem": self.meu_id,
            "prioridade": prioridade,
            "timestamp": timestamp
        }
        for broker_id, endereco in BROKERS.items():
            if broker_id == self.meu_id:
                continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(endereco)
                sock.sendall(json.dumps(msg).encode())
                sock.close()
            except:
                pass

    def _broadcast_fila_removida(self, req_id):
        """Avisa todos que uma requisição da fila foi atendida (por req_id)."""
        msg = {
            "type": "FILA_REMOVIDA",
            "req_id": req_id
        }
        for broker_id, endereco in BROKERS.items():
            if broker_id == self.meu_id:
                continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(endereco)
                sock.sendall(json.dumps(msg).encode())
                sock.close()
            except:
                pass

    def _sincronizarFila(self):
        """
        Ao iniciar (ou reiniciar), pede a fila atual para cada peer ativo.
        Cada resposta é tratada pelo RicartAgrawala via FILA_SYNC_RESPONSE,
        que faz merge por req_id evitando duplicatas.
        """
        msg = {
            "type": "FILA_SYNC_REQUEST",
            "broker_id": self.meu_id
        }
        for broker_id, endereco in BROKERS.items():
            if broker_id == self.meu_id:
                continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(endereco)
                sock.sendall(json.dumps(msg).encode())
                sock.close()
                print(f"[{self.meu_id}] sync solicitada para {broker_id}")
            except:
                print(f"[{self.meu_id}] {broker_id} indisponível para sync")

    # ─── DESPACHO DE DRONES ───────────────────────────────────────────────────

    def requisitarDrone(self, ocorrencia, prioridade):
        with self.lock_secao:
            self.ra.pedirPermissao()

            ts = self.ra.timestamp_atual
            req_id = f"{self.meu_id}:{ts}:{uuid.uuid4().hex[:8]}"

            drone_encontrado = False
            drone_id = None
            conn = None
            dono = None

            with self.lock_drones:
                for did, info in self.drones.items():
                    if info["status"] == 0:
                        info["status"] = 1
                        info["in_use_by"] = self.meu_id
                        drone_id = did
                        conn = info["conn"]
                        dono = info["owner"]
                        drone_encontrado = True
                        break

            if not drone_encontrado or self.fila:
                req = {
                    "req_id": req_id,
                    "ocorrencia": ocorrencia,
                    "origem": self.meu_id,
                    "prioridade": prioridade,
                    "timestamp": ts
                }

                if drone_encontrado:
                    with self.lock_drones:
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None
                    drone_encontrado = False

                with self.lock_fila:
                    self.fila.append(req)
                    self.fila.sort(key=lambda r: (-r["prioridade"], r["timestamp"], r["req_id"]))
                    self.mostrarFila("REQUISIÇÃO ADICIONADA")

                self.ra.liberarRecurso()
                self._broadcast_fila(req_id, ocorrencia, prioridade, ts)
                return

            self.ra.liberarRecurso()

            self.broadcast_update(drone_id, 1, dono, self.meu_id)
            dispatch = {"type": "DISPATCH", "ocorrencia": ocorrencia}
            if conn:
                try:
                    conn.sendall(json.dumps(dispatch).encode())
                except:
                    with self.lock_drones:
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None
            else:
                msg = {"type": "EXECUTE", "drone_id": drone_id, "ocorrencia": ocorrencia}
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    sock.connect(BROKERS[dono])
                    sock.sendall(json.dumps(msg).encode())
                    sock.close()
                except:
                    with self.lock_drones:
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None

    def _atenderFila(self):
        with self.lock_fila:
            if not self.fila:
                return False
            req = self.fila[0]

        drone_id = None
        conn = None
        dono = None

        with self.lock_drones:
            for did, info in self.drones.items():
                if info["status"] == 0:
                    info["status"] = 1
                    info["in_use_by"] = self.meu_id
                    drone_id = did
                    conn = info["conn"]
                    dono = info["owner"]
                    break

        if drone_id is None:
            return False

        with self.lock_fila:
            if not self.fila or self.fila[0]["req_id"] != req["req_id"]:
                with self.lock_drones:
                    self.drones[drone_id]["status"] = 0
                    self.drones[drone_id]["in_use_by"] = None
                return False
            self.fila.pop(0)
            self.mostrarFila(f"ATENDIDA -> {req['ocorrencia']}")

        self.broadcast_update(drone_id, 1, dono, self.meu_id)
        self._broadcast_fila_removida(req["req_id"])

        dispatch = {"type": "DISPATCH", "ocorrencia": req["ocorrencia"]}
        if conn:
            try:
                conn.sendall(json.dumps(dispatch).encode())
            except:
                with self.lock_drones:
                    self.drones[drone_id]["status"] = 0
                    self.drones[drone_id]["in_use_by"] = None
        else:
            msg = {"type": "EXECUTE", "drone_id": drone_id, "ocorrencia": req["ocorrencia"]}
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(BROKERS[dono])
                sock.sendall(json.dumps(msg).encode())
                sock.close()
            except:
                with self.lock_drones:
                    self.drones[drone_id]["status"] = 0
                    self.drones[drone_id]["in_use_by"] = None

        return True

    def _processarFila(self):
        with self.lock_processamento:
            if self.processando_fila:
                return
            self.processando_fila = True

        def _tentar():
            try:
                self.ra.pedirPermissao()
                self._atenderFila()
            finally:
                self.ra.liberarRecurso()
                with self.lock_processamento:
                    self.processando_fila = False

        threading.Thread(target=_tentar, daemon=True).start()

    # ─── CONEXÃO COM DRONES ───────────────────────────────────────────────────

    def _cadastrarDrone(self, client_socket):
        try:
            mensagem = client_socket.recv(4096)
            drone = json.loads(mensagem.decode())
            if drone.get("type") == "CADASTRO":
                drone_id = drone["drone_id"]
                with self.lock_drones:
                    self.drones[drone_id] = {
                        "status": 0,
                        "owner": self.meu_id,
                        "in_use_by": None,
                        "conn": client_socket
                    }
                time.sleep(0.5)
                self.broadcast_update(drone_id, 0, self.meu_id, None)
                threading.Thread(
                    target=self._loopDrone,
                    args=(drone_id, client_socket),
                    daemon=True
                ).start()
                self._processarFila()
        except Exception as e:
            client_socket.close()

    def droneConnect(self, port):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', port))
        server.listen(10)
        while True:
            client_socket, addr = server.accept()
            threading.Thread(
                target=self._cadastrarDrone,
                args=(client_socket,),
                daemon=True
            ).start()

    def _loopDrone(self, drone_id, client_socket):
        while True:
            try:
                data = client_socket.recv(4096)
                if not data:
                    break
                drone = json.loads(data.decode())
                if drone.get("type") == "CONCLUIDO":
                    with self.lock_drones:
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None
                    self.broadcast_update(drone_id, 0, self.drones[drone_id]["owner"], None)
                    self._processarFila()
            except:
                break

        with self.lock_drones:
            self.drones.pop(drone_id, None)
        print(f"\n[{self.meu_id}] DRONE DESCONECTADO -> {drone_id}")
        self.mostrarFila("APÓS DESCONECTAR DRONE")

    # ─── CONEXÃO COM SENSORES ─────────────────────────────────────────────────

    def sensorConnect(self, port):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', port))
        server.listen(10)
        while True:
            client_socket, addr = server.accept()
            threading.Thread(
                target=self._tratarSensor,
                args=(client_socket,),
                daemon=True
            ).start()

    def _tratarSensor(self, conn):
        try:
            data = conn.recv(4096)
            msg = json.loads(data.decode())
            ocorrencia = msg["ocorrencia"]
            prioridade = msg["prioridade"]
            threading.Thread(
                target=self.requisitarDrone,
                args=(ocorrencia, prioridade),
                daemon=True
            ).start()
        except Exception as e:
            print(f"[{self.meu_id}] Erro no sensor: {e}")
        finally:
            conn.close()

    # ─── INICIALIZAÇÃO ────────────────────────────────────────────────────────

    def iniciar(self):
        threading.Thread(
            target=self.droneConnect,
            args=(PORTAS_DRONES[self.meu_id],),
            daemon=True
        ).start()
        threading.Thread(
            target=self.sensorConnect,
            args=(PORTAS_SENSORES[self.meu_id],),
            daemon=True
        ).start()
        print(f"[{self.meu_id}] broker iniciado.")

        # Aguarda o servidor RA subir e pede sync da fila aos peers
        time.sleep(1)
        self._sincronizarFila()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python broker.py <setor_a|setor_b|setor_c>")
        sys.exit(1)

    meu_id = sys.argv[1]
    if meu_id not in BROKERS:
        print(f"Setor inválido. Escolha entre: {list(BROKERS.keys())}")
        sys.exit(1)

    broker = Broker(meu_id)
    broker.iniciar()

    while True:
        time.sleep(1)