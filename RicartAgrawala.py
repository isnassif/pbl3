import socket
import threading
import json
import time

REPLY = 0
REQUEST = 1
WANTED = 0
HELD = 1
RELEASED = 2


class RicartAgrawala:

    def __init__(self, meu_id, brokers, broker_ref):
        self.broker_ref = broker_ref
        self.meu_id = meu_id
        self.brokers = brokers
        self.meu_estado = RELEASED
        self.meu_timestamp = 0
        self.lista_esperando_reply = []
        self.fila_adiados = []
        self.lock = threading.Lock()
        self.permissao_event = threading.Event()

        # sobe thread de escuta assim que instancia
        threading.Thread(target=self._receiveMessage, daemon=True).start()

    # ─── RELÓGIO DE LAMPORT ───────────────────────────────────────────────────

    def _incrementarClock(self):
        with self.lock:
            self.meu_timestamp += 1
            return self.meu_timestamp

    def _atualizarClock(self, timestamp_recebido):
        with self.lock:
            self.meu_timestamp = max(self.meu_timestamp, timestamp_recebido) + 1

    # ─── RICART-AGRAWALA ──────────────────────────────────────────────────────

    def _messageReceiver(self, message):
        msg_type = message["type"]

        # 🔥 trata DRONE_UPDATE primeiro
        if msg_type == "DRONE_UPDATE":
            with self.broker_ref.lock_drones:
                drone_id = message["drone_id"]

                if drone_id not in self.broker_ref.drones:
                    self.broker_ref.drones[drone_id] = {
                        "status": message["status"],
                        "owner": message["owner"],
                        "in_use_by": message["in_use_by"],
                        "conn": None
                    }
                else:
                    # só atualiza status e setor, mantém conn
                    self.broker_ref.drones[drone_id]["status"] = message["status"]
                    self.broker_ref.drones[drone_id]["owner"] = message["owner"]
                    self.broker_ref.drones[drone_id]["in_use_by"] = message["in_use_by"]

            return
        if msg_type == "EXECUTE":
            drone_id = message["drone_id"]
            ocorrencia = message["ocorrencia"]

            with self.broker_ref.lock_drones:
                conn = self.broker_ref.drones[drone_id]["conn"]

            if conn:
                dispatch = {
                    "type": "DISPATCH",
                    "ocorrencia": ocorrencia
                }
                conn.sendall(json.dumps(dispatch).encode())
                print(f"[{self.meu_id}] executando drone {drone_id} remotamente")

            return
        # 👇 só os outros têm esses campos
        remetente = message["broker_id"]
        timestamp = message["timestamp"]

        self._atualizarClock(timestamp)

        if msg_type == REQUEST:
            self._respostDecision(remetente, timestamp)
        elif msg_type == REPLY:
            self._receivePermission(remetente)
        

    def _respostDecision(self, remetente, timestamp):
        late = False

        if self.meu_estado == HELD:
            late = True
        elif self.meu_estado == WANTED:
            if self.meu_timestamp < timestamp:
                late = True

        with self.lock:
            if late:
                self.fila_adiados.append(remetente)
            else:
                reply = {
                    "type": REPLY,
                    "broker_id": self.meu_id,
                    "timestamp": self.meu_timestamp
                }
                self._sendMessage(remetente, reply)

    def _receivePermission(self, remetente):
        with self.lock:
            if remetente in self.lista_esperando_reply:
                self.lista_esperando_reply.remove(remetente)
            if len(self.lista_esperando_reply) == 0:
                self.permissao_event.set()

    # ─── API PÚBLICA ──────────────────────────────────────────────────────────

    def pedirPermissao(self):
        self._incrementarClock()
        self.meu_estado = WANTED

        request = {
            "type": REQUEST,
            "broker_id": self.meu_id,
            "timestamp": self.meu_timestamp
        }

        with self.lock:
            for broker_id in self.brokers:
                if broker_id != self.meu_id:
                    for broker_id in self.brokers:
                        if broker_id != self.meu_id:
                            ok = self._sendMessage(broker_id, request)
                            if ok:
                                self.lista_esperando_reply.append(broker_id)

        # se for o único broker não precisa esperar
        if len(self.lista_esperando_reply) == 0:
            self.meu_estado = HELD
            return

        for broker_id in self.brokers:
            if broker_id != self.meu_id:
                self._sendMessage(broker_id, request)

        self.permissao_event.wait()
        self.permissao_event.clear()
        self.meu_estado = HELD
        print(f"[{self.meu_id}] entrou na seção crítica")

    def liberarRecurso(self):
        self.meu_estado = RELEASED
        print(f"[{self.meu_id}] saiu da seção crítica")

        with self.lock:
            fila_copia = list(self.fila_adiados)
            self.fila_adiados.clear()

        reply = {
            "type": REPLY,
            "broker_id": self.meu_id,
            "timestamp": self.meu_timestamp
        }

        for broker_id in fila_copia:
            self._sendMessage(broker_id, reply)

    # ─── REDE ─────────────────────────────────────────────────────────────────

    def _sendMessage(self, dest, msg):
        try:
            endereco = self.brokers[dest]
            msg_json = json.dumps(msg).encode()

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)  # 🔥 importante
            sock.connect(endereco)
            sock.sendall(msg_json)
            sock.close()

            return True  # ✔ envio OK

        except:
            print(f"[{self.meu_id}] {dest} OFFLINE")
            return False  # ❌ falhou

    def _handleConnection(self, conn):
        try:
            data = conn.recv(1024).decode()
            mensagem = json.loads(data)
            self._messageReceiver(mensagem)
        except Exception as e:
            print(f"[{self.meu_id}] Erro ao tratar conexão: {e}")
        finally:
            conn.close()

    def _receiveMessage(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        minha_porta = self.brokers[self.meu_id][1]
        server.bind(('0.0.0.0', minha_porta))
        server.listen(5)
        print(f"[{self.meu_id}] escutando na porta {minha_porta}...")
        while True:
            client_socket, addr = server.accept()
            threading.Thread(
                target=self._handleConnection,
                args=(client_socket,),
                daemon=True
            ).start()