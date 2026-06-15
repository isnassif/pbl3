from RicartAgrawala import RicartAgrawala
import socket
import threading
import json
import sys
import time
import uuid
import os
import sys
from blockchain.blockchain import BlockChain
from blockchain.token import GerenciadorTokens

sys.stdout.reconfigure(line_buffering=True)

def _parse_broker_env(key, default_host, default_port):
    val = os.getenv(key)  # ex: "192.168.1.10:5001"
    if val:
        host, port = val.rsplit(":", 1)
        return (host, int(port))
    return (default_host, default_port)


BROKERS = {
    "setor_a": _parse_broker_env("BROKER_A", "127.0.0.1", 5001),
    "setor_b": _parse_broker_env("BROKER_B", "127.0.0.1", 5002),
    "setor_c": _parse_broker_env("BROKER_C", "127.0.0.1", 5003),
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

PRIORIDADE_LABEL = {1: "BAIXA", 2: "MÉDIA", 3: "ALTA"}


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
        self.blockchain = BlockChain()
        self.token = GerenciadorTokens(self.blockchain)
        # Registra emissões iniciais e minera o genesis block
        self.token.inicializar_saldos()
        self.blockchain.criar_genesis()

    def _broadcast_bloco(self):
        """Envia a chain completa para todos os outros brokers após minerar um bloco."""
        msg = {
            "type": "BLOCK_NEW",
            "broker_id": self.meu_id,
            "chain": self.blockchain.chain
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
                self._log(f"⛓  bloco #{self.blockchain.chain[-1]['index']} propagado → {broker_id}")
            except:
                self._log(f"⛓  propagação falhou → {broker_id} (offline)")

    # ─── DISPLAY ──────────────────────────────────────────────────────────────

    def _log(self, msg):
        print(f"[{self.meu_id}] {msg}")

    def _mostrar_blockchain(self):
        """Imprime a blockchain completa com saldos — útil para debug e apresentação."""
        chain = self.blockchain.chain
        print()
        print(f"  ╔{'═'*62}╗")
        print(f"  ║ {'BLOCKCHAIN — ' + self.meu_id:^60} ║")
        print(f"  ╠{'═'*62}╣")
        for bloco in chain:
            print(f"  ║  Bloco #{bloco['index']} | {bloco['timestamp'][:19]:<19} | hash_ant: {bloco['previous_hash'][:8]}… ║")
            for tx in bloco['transacoes']:
                tipo = tx.get('tipo','?')
                if tipo == 'EMISSAO':
                    print(f"  ║    💰 EMISSAO  → {tx['empresa']:<10} +{tx['valor']} créditos{' '*18}║")
                elif tipo == 'PAGAMENTO':
                    req = tx.get('req_id','')[:8]
                    print(f"  ║    💸 PAGAMENTO→ {tx['empresa']:<10} -{tx['valor']} créditos | req: {req}…{' '*4}║")
                elif tipo == 'LAUDO':
                    print(f"  ║    📋 LAUDO    → drone {tx.get('drone','?'):<6} | {tx.get('ocorrencia','?'):<20}║")
            if not bloco['transacoes']:
                print(f"  ║    (bloco vazio){' '*45}║")
        print(f"  ╠{'═'*62}╣")
        print(f"  ║  {'SALDOS ATUAIS':^60} ║")
        for emp, saldo in self.token.saldos.items():
            barra = '█' * (saldo // 10) + '░' * (10 - saldo // 10)
            print(f"  ║  {emp:<12} {barra} {saldo:>3} créditos{' '*14}║")
        print(f"  ║  Chain válida: {'✅ SIM' if self.blockchain.chain_valid(self.blockchain.chain) else '❌ NÃO':<55}║")
        print(f"  ╚{'═'*62}╝")
        print()

    def mostrarFila(self, evento="ATUALIZAÇÃO"):
        print()
        print(f"  ┌{'─' * 58}┐")
        print(f"  │ {'FILA COMPARTILHADA':^56} │")
        print(f"  │ evento : {evento:<47} │")
        print(f"  │ broker : {self.meu_id:<47} │")
        print(f"  ├{'─' * 4}┬{'─' * 22}┬{'─' * 10}┬{'─' * 18}┤")
        print(f"  │ {'#':^2} │ {'OCORRÊNCIA':^20} │ {'PRIOR.':^8} │ {'ORIGEM':^16} │")
        print(f"  ├{'─' * 4}┼{'─' * 22}┼{'─' * 10}┼{'─' * 18}┤")

        if not self.fila:
            print(f"  │ {'FILA VAZIA':^56} │")
        else:
            for i, r in enumerate(self.fila, start=1):
                pri_label = PRIORIDADE_LABEL.get(r['prioridade'], str(r['prioridade']))
                print(
                    f"  │ {i:^2} │ {r['ocorrencia']:^20} │ "
                    f"{pri_label:^8} │ {r['origem']:^16} │"
                )

        print(f"  └{'─' * 4}┴{'─' * 22}┴{'─' * 10}┴{'─' * 18}┘")
        print()

    # ─── BROADCAST HELPERS ────────────────────────────────────────────────────

    def broadcast_update(self, drone_id, status, owner, in_use_by):
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
                self._log(f"sync solicitada → {broker_id}")
            except:
                self._log(f"sync falhou     → {broker_id} (offline)")

    def _syncInicial(self):
        for i in range(3):
            time.sleep(3)
            self._log(f"sync inicial {i + 1}/3...")
            self._sincronizarFila()
        self._log("sync inicial concluída.")

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

                motivo = "nenhum drone livre" if not drone_encontrado else "fila não vazia"
                self._log(f"SC: enfileirando '{ocorrencia}' ({motivo})")

                with self.lock_fila:
                    self.fila.append(req)
                    self.fila.sort(key=lambda r: (-r["prioridade"], r["timestamp"], r["req_id"]))
                    self.mostrarFila(f"NOVA REQUISIÇÃO — {ocorrencia.upper()} | P{prioridade} {PRIORIDADE_LABEL[prioridade]}")

                self.ra.liberarRecurso()
                self._broadcast_fila(req_id, ocorrencia, prioridade, ts)
                return

            self.ra.liberarRecurso()

            # monta o objeto de missão para registrar no drone
            missao = {
                "req_id": req_id,
                "ocorrencia": ocorrencia,
                "origem": self.meu_id,
                "prioridade": prioridade,
                "timestamp": ts
            }

            self._log(f"DRONE {drone_id} → despachado para '{ocorrencia}' | dono: {dono}")
            self.broadcast_update(drone_id, 1, dono, self.meu_id)
            dispatch = {"type": "DISPATCH", "ocorrencia": ocorrencia}
            if conn:
                try:
                    # registra ANTES de enviar — se o drone cair, o broker sabe a missão
                    with self.lock_drones:
                        self.drones[drone_id]["ocorrencia_atual"] = missao
                    conn.sendall(json.dumps(dispatch).encode())
                except:
                    self._log(f"ERRO: falha ao enviar dispatch para drone {drone_id}")
                    with self.lock_drones:
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None
                        self.drones[drone_id]["ocorrencia_atual"] = None
            else:
                msg = {"type": "EXECUTE", "drone_id": drone_id, "ocorrencia": ocorrencia}
                try:
                    # registra ANTES de enviar
                    with self.lock_drones:
                        self.drones[drone_id]["ocorrencia_atual"] = missao
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    sock.connect(BROKERS[dono])
                    sock.sendall(json.dumps(msg).encode())
                    sock.close()
                except:
                    self._log(f"ERRO: falha ao enviar EXECUTE para broker {dono}")
                    with self.lock_drones:
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None
                        self.drones[drone_id]["ocorrencia_atual"] = None

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
            self._log("atenderFila: nenhum drone disponível no momento")
            return False

        with self.lock_fila:
            if not self.fila or self.fila[0]["req_id"] != req["req_id"]:
                with self.lock_drones:
                    self.drones[drone_id]["status"] = 0
                    self.drones[drone_id]["in_use_by"] = None
                return False

            # registra no drone ANTES de remover da fila
            with self.lock_drones:
                if drone_id in self.drones:
                    self.drones[drone_id]["ocorrencia_atual"] = req

            self.fila.pop(0)
            self.mostrarFila(f"ATENDIDA — {req['ocorrencia'].upper()} | drone: {drone_id}")

        self._log(
            f"DRONE {drone_id} → em missão: '{req['ocorrencia']}' "
            f"| P{req['prioridade']} {PRIORIDADE_LABEL[req['prioridade']]} "
            f"| origem: {req['origem']}"
        )
        self._log(
            f"  ↳ req_id: {req['req_id']} "
            f"(se este drone cair, esta requisição voltará à fila)"
        )

        self.broadcast_update(drone_id, 1, dono, self.meu_id)
        self._broadcast_fila_removida(req["req_id"])

        dispatch = {"type": "DISPATCH", "ocorrencia": req["ocorrencia"]}
        if conn:
            try:
                conn.sendall(json.dumps(dispatch).encode())
            except:
                self._log(f"ERRO: falha ao enviar dispatch para drone {drone_id}")
                with self.lock_drones:
                    self.drones[drone_id]["status"] = 0
                    self.drones[drone_id]["in_use_by"] = None
                    self.drones[drone_id]["ocorrencia_atual"] = None
        else:
            msg = {"type": "EXECUTE", "drone_id": drone_id, "ocorrencia": req["ocorrencia"]}
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(BROKERS[dono])
                sock.sendall(json.dumps(msg).encode())
                sock.close()
            except:
                self._log(f"ERRO: falha ao enviar EXECUTE para broker {dono}")
                with self.lock_drones:
                    self.drones[drone_id]["status"] = 0
                    self.drones[drone_id]["in_use_by"] = None
                    self.drones[drone_id]["ocorrencia_atual"] = None

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
                        "conn": client_socket,
                        "ocorrencia_atual": None
                    }
                self._log(f"DRONE CONECTADO → {drone_id} (registrado em {self.meu_id})")
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
                        missao = self.drones[drone_id].get("ocorrencia_atual")
                        self.drones[drone_id]["status"] = 0
                        self.drones[drone_id]["in_use_by"] = None
                        self.drones[drone_id]["ocorrencia_atual"] = None
                    if missao:
                        self.blockchain.adicionar_transacao({
                            "tipo": "LAUDO",
                            "drone": drone_id,
                            "ocorrencia": missao["ocorrencia"],
                            "origem": missao["origem"],
                            "req_id": missao["req_id"]
                        })
                        bloco_anterior = self.blockchain.print_previous_block()
                        proof = self.blockchain.proof_of_work(bloco_anterior['proof'])
                        hash_anterior = self.blockchain.hash(bloco_anterior)
                        bloco = self.blockchain.create_block(proof, hash_anterior)
                        self._log(f"laudo gravado → bloco {bloco['index']} | cadeia válida: {self.blockchain.chain_valid(self.blockchain.chain)}")
                        # TESTE DE ADULTERAÇÃO
                        if len(self.blockchain.chain) >= 2:

                            print("\n=== TESTE DE ADULTERAÇÃO ===")

                            print(
                                "Antes:",
                                self.blockchain.chain_valid(self.blockchain.chain)
                            )

                            self.blockchain.chain[1]["transacoes"][0]["valor"] = 9999

                            print(
                                "Depois:",
                                self.blockchain.chain_valid(self.blockchain.chain)
                            )

                            print("===========================\n")
                        self._mostrar_blockchain()
                        self._broadcast_bloco()
                    ocorrencia_str = missao["ocorrencia"] if missao else "?"
                    self._log(
                        f"DRONE {drone_id} → missão '{ocorrencia_str}' CONCLUÍDA ✓ "
                        f"— drone disponível novamente"
                    )
                    self.broadcast_update(drone_id, 0, self.drones[drone_id]["owner"], None)
                    self._processarFila()
            except:
                break

        # ── drone desconectou ──
        req_perdida = None
        with self.lock_drones:
            info = self.drones.pop(drone_id, None)
            if info and info.get("ocorrencia_atual"):
                req_perdida = info["ocorrencia_atual"]

        print()
        print(f"  ╔{'═' * 56}╗")
        if req_perdida:
            print(f"  ║ {'⚠  DRONE CAIU DURANTE MISSÃO':^54} ║")
            print(f"  ╠{'═' * 56}╣")
            print(f"  ║  drone      : {drone_id:<40} ║")
            print(f"  ║  ocorrência : {req_perdida['ocorrencia']:<40} ║")
            pri = req_perdida['prioridade']
            print(f"  ║  prioridade : P{pri} {PRIORIDADE_LABEL[pri]:<37} ║")
            print(f"  ║  origem     : {req_perdida['origem']:<40} ║")
            print(f"  ║  req_id     : {req_perdida['req_id']:<40} ║")
            print(f"  ╠{'═' * 56}╣")
            print(f"  ║  {'→ REQUISIÇÃO DEVOLVIDA À FILA':^54} ║")
            print(f"  ║  {'outros brokers serão notificados':^54} ║")
        else:
            print(f"  ║ {'DRONE DESCONECTADO (sem missão ativa)':^54} ║")
            print(f"  ╠{'═' * 56}╣")
            print(f"  ║  drone : {drone_id:<46} ║")
        print(f"  ╚{'═' * 56}╝")
        print()

        if req_perdida:
            with self.lock_fila:
                self.fila.insert(0, req_perdida)
                self.fila.sort(key=lambda r: (-r["prioridade"], r["timestamp"], r["req_id"]))
                self.mostrarFila(f"RECUPERAÇÃO — '{req_perdida['ocorrencia']}' voltou à fila")
            self._broadcast_fila(
                req_perdida["req_id"],
                req_perdida["ocorrencia"],
                req_perdida["prioridade"],
                req_perdida["timestamp"]
            )
            self._log("broadcast enviado — outros brokers atualizaram a fila")

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
            origem = msg.get("origem", self.meu_id)
            req_id = str(uuid.uuid4())
            if prioridade == 1:
                valor_gasto = 2
            elif prioridade == 2:
                valor_gasto = 5
            elif prioridade == 3:
                valor_gasto = 10
            else:
                print("Sem prioridade quebrou")
                return
            
            credito_aceito = self.token.gastar(origem, valor_gasto,ocorrencia,req_id)
            print("Pendentes:", self.blockchain.transacoes_pendentes)
            if not credito_aceito:
                self._log(
                    f"CRÉDITO NEGADO → {origem} sem saldo suficiente"
                )
                return
            bloco_anterior = self.blockchain.print_previous_block()

            proof = self.blockchain.proof_of_work(
                bloco_anterior['proof']
            )

            hash_anterior = self.blockchain.hash(
                bloco_anterior
            )

            self.blockchain.create_block(
                proof,
                hash_anterior
            )
            self._log(
                f"CRÉDITO OK → {origem} debitado {valor_gasto} créditos "
                f"(saldo restante: {self.token.consultar_saldo(origem)}) "
                f"| req_id: {req_id[:8]}…"
            )
            self._mostrar_blockchain()
            self._broadcast_bloco()
            self._log(
                f"SENSOR → '{ocorrencia}' "
                f"| P{prioridade} {PRIORIDADE_LABEL[prioridade]}"
            )
            threading.Thread(
                target=self.requisitarDrone,
                args=(ocorrencia, prioridade),
                daemon=True
            ).start()
        except Exception as e:
            self._log(f"ERRO no sensor: {e}")
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
        threading.Thread(
            target=self._syncInicial,
            daemon=True
        ).start()

        print()
        print(f"  ┌{'─' * 48}┐")
        print(f"  │ {'BROKER INICIADO':^46} │")
        print(f"  │ {'setor : ' + self.meu_id:<46} │")
        print(f"  ├{'─' * 48}┤")
        for bid, (host, port) in BROKERS.items():
            marker = "◄ EU" if bid == self.meu_id else "    "
            print(f"  │  {marker}  {bid} → {host}:{port:<20} │")
        print(f"  └{'─' * 48}┘")
        print()


if __name__ == "__main__":
    meu_id = sys.argv[1] if len(sys.argv) > 1 else os.getenv("MEU_SETOR", "")

    if not meu_id or meu_id not in BROKERS:
        print("Uso: python broker.py <setor_a|setor_b|setor_c>")
        print("  ou: MEU_SETOR=setor_a python broker.py")
        sys.exit(1)

    broker = Broker(meu_id)
    broker.iniciar()

    while True:
        time.sleep(1)
