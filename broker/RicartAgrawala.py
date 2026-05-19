import socket
import threading
import json
import time

REPLY = "REPLY"
REQUEST = "REQUEST"

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

        threading.Thread(target=self._receiveMessage, daemon=True).start()

    # ─── RELÓGIO DE LAMPORT ───────────────────────────────────────────────────

    @property
    def timestamp_atual(self):
        with self.lock:
            return self.meu_timestamp

    def _incrementarClock(self):
        with self.lock:
            self.meu_timestamp += 1
            return self.meu_timestamp

    def _atualizarClock(self, timestamp_recebido):
        with self.lock:
            self.meu_timestamp = max(self.meu_timestamp, timestamp_recebido) + 1

    # ─── ROTEADOR DE MENSAGENS ────────────────────────────────────────────────

    def _messageReceiver(self, message):
        msg_type = message.get("type")

        # ── Mensagens de aplicação ──

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
                    self.broker_ref.drones[drone_id]["status"] = message["status"]
                    self.broker_ref.drones[drone_id]["owner"] = message["owner"]
                    self.broker_ref.drones[drone_id]["in_use_by"] = message["in_use_by"]
            return

        if msg_type == "EXECUTE":
            drone_id = message["drone_id"]
            ocorrencia = message["ocorrencia"]
            with self.broker_ref.lock_drones:
                conn = self.broker_ref.drones.get(drone_id, {}).get("conn")
            if conn:
                dispatch = {"type": "DISPATCH", "ocorrencia": ocorrencia}
                try:
                    conn.sendall(json.dumps(dispatch).encode())
                except Exception as e:
                    print(f"[{self.meu_id}] Erro ao executar drone {drone_id}: {e}")
            return

        if msg_type == "FILA_REQUISICAO":
            req = {
                "req_id": message["req_id"],
                "ocorrencia": message["ocorrencia"],
                "origem": message["origem"],
                "prioridade": message["prioridade"],
                "timestamp": message["timestamp"]
            }

            adicionou = False

            with self.broker_ref.lock_fila:

                ids = {
                    r["req_id"]
                    for r in self.broker_ref.fila
                }

                if req["req_id"] not in ids:
                    self.broker_ref.fila.append(req)
                    adicionou = True

                self.broker_ref.fila.sort(
                    key=lambda r:
                    (-r["prioridade"],
                    r["timestamp"],
                    r["req_id"])
                )

            if adicionou:
                self.broker_ref.mostrarFila(
                    f"NOVA REQUISIÇÃO REMOTA — {req['origem']}"
                )

                self.broker_ref._processarFila()

            return

        if msg_type == "FILA_REMOVIDA":
            req_id = message["req_id"]
            with self.broker_ref.lock_fila:
                self.broker_ref.fila = [
                    r for r in self.broker_ref.fila
                    if r["req_id"] != req_id
                ]
            return

        if msg_type == "BROKER_OFFLINE":
            broker_caido = message["broker_id"]
            with self.broker_ref.lock_fila:
                self.broker_ref.fila = [
                    r for r in self.broker_ref.fila
                    if r["origem"] != broker_caido
                ]
            print(f"[{self.meu_id}] fila limpa para {broker_caido} (broadcast offline)")
            self.broker_ref.mostrarFila(f"{broker_caido} OFFLINE")
            return

        if msg_type == "FILA_SYNC_REQUEST":
            remetente_id = message.get("broker_id")
            with self.broker_ref.lock_fila:
                fila_atual = list(self.broker_ref.fila)
            resposta = {
                "type": "FILA_SYNC_RESPONSE",
                "broker_id": self.meu_id,
                "fila": fila_atual
            }
            self._sendMessage(remetente_id, resposta)
            return

        if msg_type == "FILA_SYNC_RESPONSE":
            fila_recebida = message.get("fila", [])
            with self.broker_ref.lock_fila:
                ids_locais = {r["req_id"] for r in self.broker_ref.fila}
                for req in fila_recebida:
                    if req["req_id"] not in ids_locais:
                        self.broker_ref.fila.append(req)
                self.broker_ref.fila.sort(
                    key=lambda r: (-r["prioridade"], r["timestamp"], r["req_id"])
                )
            self.broker_ref.mostrarFila("SYNC RECEBIDA")
            return

        # ── Mensagens de controle do Ricart-Agrawala ──
        remetente = message.get("broker_id")
        timestamp = message.get("timestamp", 0)

        self._atualizarClock(timestamp)

        if msg_type == REQUEST:
            self._respostDecision(remetente, timestamp)
        elif msg_type == REPLY:
            self._receivePermission(remetente)

    # ─── RICART-AGRAWALA ──────────────────────────────────────────────────────

    def _respostDecision(self, remetente, timestamp):
        late = False

        if self.meu_estado == HELD:
            late = True
        elif self.meu_estado == WANTED:
            if (self.meu_timestamp, self.meu_id) < (timestamp, remetente):
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
            self.lista_esperando_reply.clear()
            for broker_id in self.brokers:
                if broker_id != self.meu_id:
                    ok = self._sendMessage(broker_id, request)
                    if ok:
                        self.lista_esperando_reply.append(broker_id)

        if len(self.lista_esperando_reply) == 0:
            self.meu_estado = HELD
            return

        self.permissao_event.wait()
        self.permissao_event.clear()
        self.meu_estado = HELD

    def liberarRecurso(self):
        self.meu_estado = RELEASED

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

    def _removerRequisicoesBrokerCaido(self, broker_id):
        with self.broker_ref.lock_fila:
            antes = len(self.broker_ref.fila)
            self.broker_ref.fila = [
                r for r in self.broker_ref.fila
                if r["origem"] != broker_id
            ]
            depois = len(self.broker_ref.fila)

        if antes != depois:
            print(f"[{self.meu_id}] removidas {antes - depois} requisições de {broker_id} (offline)")
            self.broker_ref.mostrarFila(f"{broker_id} OFFLINE")
            self._broadcastBrokerCaido(broker_id)

    def _broadcastBrokerCaido(self, broker_id_caido):
        msg = {
            "type": "BROKER_OFFLINE",
            "broker_id": broker_id_caido
        }
        for bid, endereco in self.brokers.items():
            if bid == self.meu_id or bid == broker_id_caido:
                continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(endereco)
                sock.sendall(json.dumps(msg).encode())
                sock.close()
            except:
                pass

    def _sendMessage(self, dest, msg):
        try:
            endereco = self.brokers[dest]
            msg_json = json.dumps(msg).encode()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(endereco)
            sock.sendall(msg_json)
            sock.close()
            return True
        except:
            print(f"[{self.meu_id}] {dest} OFFLINE")
            self._removerRequisicoesBrokerCaido(dest)
            return False

    def _handleConnection(self, conn):
        try:
            data = b''

            while True:
                parte = conn.recv(4096)

                if not parte:
                    break

                data += parte

            if not data:
                return

            mensagem = json.loads(data.decode())

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
        server.listen(10)
        print(f"[{self.meu_id}] escutando na porta {minha_porta}...")
        while True:
            client_socket, addr = server.accept()
            threading.Thread(
                target=self._handleConnection,
                args=(client_socket,),
                daemon=True
            ).start()