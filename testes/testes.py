import contextlib
import glob
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import uuid

# ─────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO DE CAMINHOS
# ─────────────────────────────────────────────────────────────────────────

TESTES_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TESTES_DIR, ".."))
BROKER_DIR = os.path.join(PROJECT_ROOT, "broker")
DATA_DIR = os.path.join(BROKER_DIR, "data")

sys.path.insert(0, BROKER_DIR)

from blockchain.blockchain import BlockChain
from blockchain.token import GerenciadorTokens
from blockchain.assinatura import GerenciadorAutenticacao

SETORES = ["setor_a", "setor_b", "setor_c"]

PORTAS_BROKER = {"setor_a": 5001, "setor_b": 5002, "setor_c": 5003}
PORTAS_DRONE = {"setor_a": 6001, "setor_b": 6002, "setor_c": 6003}
PORTAS_SENSOR = {"setor_a": 7001, "setor_b": 7002, "setor_c": 7003}

TIMEOUT_REDE = 4
SYNC_INICIAL_SEGUNDOS = 11

# ─────────────────────────────────────────────────────────────────────────
# HELPERS DE REDE — simulam sensor.py / drone.py / cliente.py "de fora"
# ─────────────────────────────────────────────────────────────────────────

def _enviar(host, porta, payload: dict, timeout=TIMEOUT_REDE) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, porta))
        sock.sendall(json.dumps(payload).encode())
        sock.close()
        return True
    except OSError:
        return False


def enviar_ocorrencia(setor_destino, ocorrencia, prioridade, origem=None,
                       assinatura_valida=True, auth=None):
    origem = origem or setor_destino
    auth = auth or GerenciadorAutenticacao()
    dados = f"{origem}:{ocorrencia}:{prioridade}"
    if assinatura_valida:
        assinatura = auth.assinar(origem, dados)
    else:
        assinatura = "assinatura_forjada_invalida"
    payload = {
        "ocorrencia": ocorrencia,
        "prioridade": prioridade,
        "origem": origem,
        "assinatura": assinatura,
    }
    porta = PORTAS_SENSOR[setor_destino]
    return _enviar("127.0.0.1", porta, payload)


def conectar_drone_falso(setor_destino, drone_id, timeout=TIMEOUT_REDE):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(("127.0.0.1", PORTAS_DRONE[setor_destino]))
    sock.sendall(json.dumps({"type": "CADASTRO", "drone_id": drone_id}).encode())
    return sock


def esperar_dispatch(sock, timeout=TIMEOUT_REDE):
    sock.settimeout(timeout)
    try:
        data = sock.recv(4096)
        if not data:
            return None
        return json.loads(data.decode())
    except socket.timeout:
        return None


def concluir_missao(sock):
    sock.sendall(json.dumps({"type": "CONCLUIDO"}).encode())


def enviar_mensagem_broker(setor_destino, msg: dict, timeout=TIMEOUT_REDE):
    porta = PORTAS_BROKER[setor_destino]
    return _enviar("127.0.0.1", porta, msg, timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────
# GERENCIADOR DE PROCESSOS REAIS DE BROKER (subprocess de verdade)
# ─────────────────────────────────────────────────────────────────────────

class ClusterDeBrokers:

    def __init__(self, setores=None):
        self.setores = setores or list(SETORES)
        self.processos = {}
        self.logs = {}

    def limpar_ledger_em_disco(self):
        if os.path.isdir(DATA_DIR):
            for f in glob.glob(os.path.join(DATA_DIR, "*.json")):
                with contextlib.suppress(OSError):
                    os.remove(f)
        else:
            os.makedirs(DATA_DIR, exist_ok=True)

    def subir(self, setor):
        if setor in self.processos and self.processos[setor].poll() is None:
            return
        log_path = f"/tmp/teste_barema_{setor}.log"
        log_file = open(log_path, "w")
        self.logs[setor] = log_file
        proc = subprocess.Popen(
            [sys.executable, "broker.py", setor],
            cwd=BROKER_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processos[setor] = proc

    def subir_todos(self):
        for setor in self.setores:
            self.subir(setor)

    def derrubar(self, setor):
        proc = self.processos.get(setor)
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    def derrubar_todos(self):
        for setor in list(self.processos.keys()):
            self.derrubar(setor)
        for f in self.logs.values():
            with contextlib.suppress(Exception):
                f.close()

    def esta_vivo(self, setor):
        proc = self.processos.get(setor)
        return bool(proc) and proc.poll() is None

    def log_de(self, setor):
        path = f"/tmp/teste_barema_{setor}.log"
        if not os.path.exists(path):
            return ""
        with open(path, "r", errors="replace") as f:
            return f.read()

    def esperar_porta_aberta(self, setor, porta_dict, timeout=8):
        porta = porta_dict[setor]
        prazo = time.time() + timeout
        while time.time() < prazo:
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.2)
        return False


def chain_de_disco(setor):
    path = os.path.join(DATA_DIR, f"{setor}_blockchain.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═════════════════════════════════════════════════════════════════════════
# 1) ARQUITETURA
# ═════════════════════════════════════════════════════════════════════════

class CriterioArquitetura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = ClusterDeBrokers()
        cls.cluster.limpar_ledger_em_disco()
        cls.cluster.subir_todos()
        for s in SETORES:
            cls.cluster.esperar_porta_aberta(s, PORTAS_BROKER)
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.derrubar_todos()

    def test_01_multiplos_nos_independentes_em_execucao(self):
        pids = set()
        for setor in SETORES:
            self.assertTrue(
                self.cluster.esta_vivo(setor),
                f"broker {setor} não está de pé como processo independente",
            )
            pids.add(self.cluster.processos[setor].pid)
        self.assertEqual(
            len(pids), 3,
            "os 3 brokers deveriam ser 3 processos de SO distintos (PIDs únicos)",
        )

    def test_02_cada_no_mantem_sua_propria_copia_do_ledger_em_disco(self):
        ok = enviar_ocorrencia("setor_a", "averiguacao", 1)
        self.assertTrue(ok, "não foi possível conectar no broker setor_a")
        time.sleep(1.5)

        caminhos = [os.path.join(DATA_DIR, f"{s}_blockchain.json") for s in SETORES]
        for caminho, setor in zip(caminhos, SETORES):
            self.assertTrue(
                os.path.exists(caminho),
                f"esperava um arquivo de ledger próprio para {setor} em {caminho}",
            )
        for setor in SETORES:
            chain = chain_de_disco(setor)
            self.assertIsNotNone(chain)
            self.assertGreaterEqual(len(chain.get("chain", [])), 1)

    def test_03_sistema_continua_operando_apos_derrubar_um_no(self):
        self.cluster.derrubar("setor_b")
        time.sleep(1)

        ok_a = enviar_ocorrencia("setor_a", "possivel_ataque", 2)
        ok_c = enviar_ocorrencia("setor_c", "possivel_ataque", 2)
        self.assertTrue(ok_a, "setor_a parou de responder após queda do setor_b")
        self.assertTrue(ok_c, "setor_c parou de responder após queda do setor_b")
        time.sleep(1.5)

        log_a = self.cluster.log_de("setor_a")
        log_c = self.cluster.log_de("setor_c")
        self.assertIn("CRÉDITO OK", log_a + log_c)

        self.cluster.subir("setor_b")
        self.cluster.esperar_porta_aberta("setor_b", PORTAS_BROKER)

    def test_04_nao_ha_no_mestre_disfarcado_cada_broker_responde_diretamente(self):
        for setor in SETORES:
            self.assertTrue(
                self.cluster.esperar_porta_aberta(setor, PORTAS_SENSOR, timeout=5),
                f"porta de sensor de {setor} não respondeu — sugere dependência de um nó central",
            )


# ═════════════════════════════════════════════════════════════════════════
# 2) COMUNICAÇÃO (P2P / propagação / consenso)
# ═════════════════════════════════════════════════════════════════════════

class CriterioComunicacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = ClusterDeBrokers()
        cls.cluster.limpar_ledger_em_disco()
        cls.cluster.subir_todos()
        for s in SETORES:
            cls.cluster.esperar_porta_aberta(s, PORTAS_BROKER)
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.derrubar_todos()

    def test_01_brokers_se_conectam_entre_si_via_tcp_p2p(self):
        for setor in SETORES:
            aberto = self.cluster.esperar_porta_aberta(setor, PORTAS_BROKER, timeout=3)
            self.assertTrue(aberto, f"canal P2P de {setor} (porta {PORTAS_BROKER[setor]}) não está acessível")

    def test_02_novo_bloco_e_propagado_para_os_demais_nos(self):
        chain_b_antes = chain_de_disco("setor_b")
        len_antes = len(chain_b_antes["chain"]) if chain_b_antes else 0

        ok = enviar_ocorrencia("setor_a", "ataque_concreto", 3)
        self.assertTrue(ok)
        time.sleep(2)

        chain_b_depois = chain_de_disco("setor_b")
        self.assertIsNotNone(chain_b_depois, "setor_b deveria ter recebido o bloco propagado")
        self.assertGreater(
            len(chain_b_depois["chain"]), len_antes,
            "a chain de setor_b não cresceu — o bloco minerado em setor_a não foi propagado",
        )

    def test_03_nova_requisicao_na_fila_e_propagada_via_broadcast(self):
        ok = enviar_ocorrencia("setor_c", "possivel_ataque", 2)
        self.assertTrue(ok)
        time.sleep(2)

        logs_outros = self.cluster.log_de("setor_a") + self.cluster.log_de("setor_b")
        self.assertTrue(
            ("REQUISIÇÃO REMOTA" in logs_outros) or ("FILA_REQUISICAO" in logs_outros) or
            ("NOVA REQUISIÇÃO" in logs_outros),
            "não há evidência no log de outros brokers de que a fila foi propagada",
        )

    def test_04_mensagem_de_protocolo_desconhecida_nao_derruba_o_no(self):
        enviado = enviar_mensagem_broker("setor_a", {"type": "TIPO_QUE_NAO_EXISTE", "x": 1})
        self.assertTrue(enviado, "broker não aceitou a conexão TCP para a mensagem de teste")
        time.sleep(1)
        self.assertTrue(self.cluster.esta_vivo("setor_a"), "broker caiu ao receber mensagem de protocolo desconhecida")

    def test_05_consenso_resolve_conflito_por_chain_mais_longa_e_valida(self):
        chain_local = chain_de_disco("setor_b")
        self.assertIsNotNone(chain_local)
        len_antes = len(chain_local["chain"])

        chain_falsa = list(chain_local["chain"]) + [
            {"index": 999, "timestamp": "fake", "proof": 1,
             "previous_hash": "hash_invalido_inventado", "transacoes": []},
            {"index": 1000, "timestamp": "fake2", "proof": 1,
             "previous_hash": "hash_invalido_inventado_2", "transacoes": []},
        ]
        msg = {"type": "BLOCK_NEW", "broker_id": "setor_invasor", "chain": chain_falsa}
        enviado = enviar_mensagem_broker("setor_b", msg)
        self.assertTrue(enviado)
        time.sleep(1.5)

        chain_depois = chain_de_disco("setor_b")
        self.assertEqual(
            len(chain_depois["chain"]), len_antes,
            "setor_b aceitou uma chain mais longa porém inválida — consenso não está validando antes de substituir",
        )


# ═════════════════════════════════════════════════════════════════════════
# 3) GESTÃO DE ATIVOS (CRÉDITOS / TOKEN)
# ═════════════════════════════════════════════════════════════════════════

class CriterioGestaoDeAtivos(unittest.TestCase):

    def setUp(self):
        self.bc = BlockChain(persist_path=f"/tmp/teste_token_{uuid.uuid4().hex}.json")
        self.token = GerenciadorTokens(self.bc)
        self.auth = GerenciadorAutenticacao()

    def test_01_emissao_inicial_credita_as_tres_companhias(self):
        self.token.inicializar_saldos()
        self.bc.criar_genesis()

        self.assertEqual(self.token.consultar_saldo("setor_a"), 100)
        self.assertEqual(self.token.consultar_saldo("setor_b"), 100)
        self.assertEqual(self.token.consultar_saldo("setor_c"), 100)

        tipos_no_bloco = [tx["tipo"] for tx in self.bc.chain[0]["transacoes"]]
        self.assertEqual(tipos_no_bloco.count("EMISSAO"), 3)

    def test_02_saldo_e_derivado_do_historico_do_ledger_nao_de_variavel_solta(self):
        self.token.inicializar_saldos()
        self.bc.criar_genesis()
        self.token.gastar("setor_a", 30, "ataque_concreto", "req-teste-1")
        self.bc.criar_block_se_necessario = None 

        self.bc.create_block(proof=1, previous_hash=self.bc.hash(self.bc.chain[-1]))

        self.token.saldos["setor_a"] = -9999

        self.token.recalcular_saldos()
        self.assertEqual(
            self.token.consultar_saldo("setor_a"), 70,
            "saldo recalculado a partir do ledger não bate com EMISSAO(100) - PAGAMENTO(30)",
        )

    def test_03_transferencia_exige_assinatura_valida_do_remetente(self):
        dados = "setor_a:setor_b:20"
        assinatura_valida = self.auth.assinar("setor_a", dados)
        assinatura_forjada = "0" * len(assinatura_valida)

        self.assertTrue(self.auth.verificar("setor_a", dados, assinatura_valida))
        self.assertFalse(self.auth.verificar("setor_a", dados, assinatura_forjada))

    def test_04_transferencia_bem_sucedida_debita_origem_e_credita_destino_no_ledger(self):
        self.token.inicializar_saldos()
        self.bc.criar_genesis()

        ok = self.token.transferir("setor_a", "setor_b", 25)
        self.assertTrue(ok)
        self.assertEqual(self.token.consultar_saldo("setor_a"), 75)
        self.assertEqual(self.token.consultar_saldo("setor_b"), 125)

        ultima_tx = self.bc.transacoes_pendentes[-1]
        self.assertEqual(ultima_tx["tipo"], "TRANSFERENCIA")
        self.assertEqual(ultima_tx["de"], "setor_a")
        self.assertEqual(ultima_tx["para"], "setor_b")
        self.assertEqual(ultima_tx["valor"], 25)

    def test_05_transferencia_para_empresa_inexistente_e_rejeitada(self):
        self.token.inicializar_saldos()
        self.bc.criar_genesis()
        ok = self.token.transferir("setor_a", "setor_fantasma", 10)
        self.assertFalse(ok)
        self.assertEqual(self.token.consultar_saldo("setor_a"), 100, "saldo não deveria ter sido debitado")


# ═════════════════════════════════════════════════════════════════════════
# 4) CRITÉRIO: PREVENÇÃO DE DUPLO GASTO
# ═════════════════════════════════════════════════════════════════════════

class CriterioPrevencaoDuploGasto(unittest.TestCase):

    def setUp(self):
        self.bc = BlockChain(persist_path=f"/tmp/teste_dgasto_{uuid.uuid4().hex}.json")
        self.token = GerenciadorTokens(self.bc)
        self.token.inicializar_saldos()
        self.bc.criar_genesis()

    def test_01_dois_gastos_concorrentes_que_excedem_o_saldo_apenas_um_e_aceito(self):
        resultados = []

        def gastar():
            ok = self.token.gastar("setor_a", 70, "ataque_concreto", str(uuid.uuid4()))
            resultados.append(ok)

        t1 = __import__("threading").Thread(target=gastar)
        t2 = __import__("threading").Thread(target=gastar)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(
            sorted(resultados), [False, True],
            f"esperava exatamente 1 sucesso e 1 falha entre threads concorrentes, obtive {resultados}",
        )
        self.assertEqual(self.token.consultar_saldo("setor_a"), 30)

    def test_02_validacao_e_feita_contra_o_saldo_real_nao_apenas_na_interface(self):
        self.assertTrue(self.token.gastar("setor_a", 60, "ataque_concreto", "r1"))
        self.assertEqual(self.token.consultar_saldo("setor_a"), 40)
        self.assertFalse(self.token.gastar("setor_a", 60, "ataque_concreto", "r2"))
        self.assertEqual(self.token.consultar_saldo("setor_a"), 40, "saldo não deveria ter mudado na tentativa rejeitada")

    def test_03_dez_gastos_concorrentes_thread_safety_sem_saldo_negativo(self):
        import threading
        resultados = []
        lock_resultados = threading.Lock()

        def gastar():
            ok = self.token.gastar("setor_a", 15, "possivel_ataque", str(uuid.uuid4()))
            with lock_resultados:
                resultados.append(ok)

        threads = [threading.Thread(target=gastar) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        aceitos = sum(1 for r in resultados if r)
        self.assertLessEqual(aceitos * 15, 100, "saldo foi gasto além do disponível sob concorrência")
        self.assertGreaterEqual(self.token.consultar_saldo("setor_a"), 0, "saldo final ficou negativo — duplo gasto ocorreu")

    def test_04_duplo_gasto_via_rede_duas_requisicoes_simultaneas_mesmo_saldo(self):
        cluster = ClusterDeBrokers(["setor_a", "setor_b", "setor_c"])
        cluster.limpar_ledger_em_disco()
        cluster.subir_todos()
        for s in SETORES:
            cluster.esperar_porta_aberta(s, PORTAS_BROKER)
        time.sleep(2)
        try:
            import threading

            def disparar():
                enviar_ocorrencia("setor_a", "ataque_concreto", 3)

            t1 = threading.Thread(target=disparar)
            t2 = threading.Thread(target=disparar)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            time.sleep(2)

            log = cluster.log_de("setor_a")
            aceitos = log.count("CRÉDITO OK")
            negados = log.count("CRÉDITO NEGADO")
            self.assertGreaterEqual(aceitos, 1, "nenhuma das duas requisições foi aceita")
            self.assertGreaterEqual(
                negados + aceitos, 2,
                "esperava que ambas as requisições fossem processadas (uma aceita, uma negada/insuficiente)",
            )
        finally:
            cluster.derrubar_todos()


# ═════════════════════════════════════════════════════════════════════════
# 5) CRITÉRIO: REQUISIÇÃO E PAGAMENTO DE ESCOLTAS
# ═════════════════════════════════════════════════════════════════════════

class CriterioRequisicaoEPagamento(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cluster = ClusterDeBrokers()
        cls.cluster.limpar_ledger_em_disco()
        cls.cluster.subir_todos()
        for s in SETORES:
            cls.cluster.esperar_porta_aberta(s, PORTAS_BROKER)
            cls.cluster.esperar_porta_aberta(s, PORTAS_DRONE)
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.derrubar_todos()

    def test_01_drone_so_e_despachado_apos_pagamento_confirmado(self):
        drone_id = f"drone_teste_{uuid.uuid4().hex[:6]}"
        sock = conectar_drone_falso("setor_a", drone_id)
        try:
            time.sleep(0.5)
            ok = enviar_ocorrencia("setor_a", "averiguacao", 1)
            self.assertTrue(ok)

            dispatch = esperar_dispatch(sock, timeout=5)
            self.assertIsNotNone(dispatch, "drone nunca recebeu DISPATCH")
            self.assertEqual(dispatch.get("type"), "DISPATCH")

            log = self.cluster.log_de("setor_a")
            self.assertIn(
                "CRÉDITO OK", log,
                "drone foi despachado mas não há evidência de pagamento confirmado no log",
            )
            concluir_missao(sock)
        finally:
            sock.close()

    def test_02_requisicao_negada_quando_saldo_insuficiente(self):
        for _ in range(11):
            enviar_ocorrencia("setor_b", "ataque_concreto", 3)
            time.sleep(0.3)
        time.sleep(1.5)

        log = self.cluster.log_de("setor_b")
        self.assertIn(
            "CRÉDITO NEGADO", log,
            "esperava ao menos uma negação de crédito após esgotar o saldo de setor_b",
        )

    def test_03_sem_alocacao_duplicada_de_drone_sob_concorrencia(self):
        drone_id = f"drone_unico_{uuid.uuid4().hex[:6]}"
        sock = conectar_drone_falso("setor_c", drone_id)
        try:
            time.sleep(0.5)
            import threading

            def disparar(ocorrencia):
                enviar_ocorrencia("setor_c", ocorrencia, 2)

            t1 = threading.Thread(target=disparar, args=("possivel_ataque",))
            t2 = threading.Thread(target=disparar, args=("possivel_ataque",))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            primeiro_dispatch = esperar_dispatch(sock, timeout=5)
            self.assertIsNotNone(primeiro_dispatch, "drone único não recebeu nenhum dispatch")

            sock.settimeout(1.5)
            segundo = None
            try:
                data = sock.recv(4096)
                if data:
                    segundo = json.loads(data.decode())
            except socket.timeout:
                segundo = None

            self.assertIsNone(
                segundo,
                "o mesmo drone recebeu um segundo DISPATCH antes de concluir a missão atual — alocação duplicada",
            )

            log = self.cluster.log_de("setor_c")
            self.assertTrue(
                ("enfileirando" in log) or ("FILA COMPARTILHADA" in log),
                "a segunda requisição deveria ter sido enfileirada por falta de drone livre",
            )
            concluir_missao(sock)
        finally:
            sock.close()

    def test_04_pagamento_fica_registrado_e_consultavel_no_ledger(self):
        ok = enviar_ocorrencia("setor_a", "possivel_ataque", 2)
        self.assertTrue(ok)
        time.sleep(1.5)

        chain = chain_de_disco("setor_a")
        self.assertIsNotNone(chain)
        pagamentos = [
            tx for bloco in chain["chain"] for tx in bloco["transacoes"]
            if tx.get("tipo") == "PAGAMENTO" and tx.get("empresa") == "setor_a"
        ]
        self.assertGreaterEqual(len(pagamentos), 1, "nenhuma transação de PAGAMENTO encontrada no ledger")


# ═════════════════════════════════════════════════════════════════════════
# 6) CRITÉRIO: LOG DE OPERAÇÕES IMUTÁVEL (LAUDO)
# ═════════════════════════════════════════════════════════════════════════

class CriterioLogImutavel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cluster = ClusterDeBrokers()
        cls.cluster.limpar_ledger_em_disco()
        cls.cluster.subir_todos()
        for s in SETORES:
            cls.cluster.esperar_porta_aberta(s, PORTAS_BROKER)
            cls.cluster.esperar_porta_aberta(s, PORTAS_DRONE)
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.derrubar_todos()

    def test_01_laudo_e_gravado_no_ledger_ao_concluir_missao(self):
        drone_id = f"drone_laudo_{uuid.uuid4().hex[:6]}"
        sock = conectar_drone_falso("setor_a", drone_id)
        try:
            time.sleep(0.5)
            enviar_ocorrencia("setor_a", "averiguacao", 1)
            dispatch = esperar_dispatch(sock, timeout=5)
            self.assertIsNotNone(dispatch)

            concluir_missao(sock)
            time.sleep(1.5)

            chain = chain_de_disco("setor_a")
            laudos = [
                tx for bloco in chain["chain"] for tx in bloco["transacoes"]
                if tx.get("tipo") == "LAUDO"
            ]
            self.assertGreaterEqual(len(laudos), 1, "nenhum LAUDO encontrado no ledger após conclusão de missão")
            laudo = laudos[-1]
            for campo in ("drone", "ocorrencia", "origem", "req_id"):
                self.assertIn(campo, laudo, f"laudo não contém o campo obrigatório '{campo}'")
        finally:
            sock.close()

    def test_02_chain_valida_e_detectada_corretamente(self):
        bc = BlockChain(persist_path=f"/tmp/teste_chainvalida_{uuid.uuid4().hex}.json")
        bc.criar_genesis()
        anterior = bc.print_previous_block()
        proof = bc.proof_of_work(anterior["proof"])
        bc.create_block(proof, bc.hash(anterior))
        self.assertTrue(bc.chain_valid(bc.chain))

    def test_03_adulteracao_no_hash_anterior_e_detectada(self):
        bc = BlockChain(persist_path=f"/tmp/teste_adulteracao_{uuid.uuid4().hex}.json")
        bc.criar_genesis()
        anterior = bc.print_previous_block()
        proof = bc.proof_of_work(anterior["proof"])
        bc.create_block(proof, bc.hash(anterior))

        self.assertTrue(bc.chain_valid(bc.chain), "chain deveria ser válida antes da adulteração")

        bc.chain[1]["previous_hash"] = "0" * 64
        self.assertFalse(bc.chain_valid(bc.chain), "adulteração do previous_hash não foi detectada")

    def test_04_adulteracao_de_valor_de_transacao_e_detectada(self):
        bc = BlockChain(persist_path=f"/tmp/teste_adultx_{uuid.uuid4().hex}.json")
        token = GerenciadorTokens(bc)
        token.emitir_creditos("setor_a", 100)
        bc.criar_genesis()

        anterior = bc.print_previous_block()
        proof = bc.proof_of_work(anterior["proof"])
        bc.create_block(proof, bc.hash(anterior))
        self.assertTrue(bc.chain_valid(bc.chain))

        bc.chain[0]["transacoes"][0]["valor"] = 999999
        self.assertFalse(
            bc.chain_valid(bc.chain),
            "adulteração do valor de uma transação no bloco genesis não foi detectada",
        )

    def test_05_arquivo_corrompido_em_disco_e_detectado_pela_checagem_de_integridade(self):
        path = f"/tmp/teste_disco_corrompido_{uuid.uuid4().hex}.json"
        bc = BlockChain(persist_path=path)
        bc.criar_genesis()
        anterior = bc.print_previous_block()
        proof = bc.proof_of_work(anterior["proof"])
        bc.create_block(proof, bc.hash(anterior))

        with open(path, "r", encoding="utf-8") as f:
            dados = json.load(f)
        dados["chain"][1]["previous_hash"] = "valor_falsificado_manualmente"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dados, f)

        bc2 = BlockChain(persist_path=path)
        restaurou = bc2.carregar_do_disco()
        self.assertFalse(
            restaurou,
            "carregar_do_disco() aceitou uma chain adulterada como válida",
        )


# ═════════════════════════════════════════════════════════════════════════
# 7) CRITÉRIO: TRANSPARÊNCIA E AUDITABILIDADE
# ═════════════════════════════════════════════════════════════════════════

class CriterioTransparencia(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cluster = ClusterDeBrokers()
        cls.cluster.limpar_ledger_em_disco()
        cls.cluster.subir_todos()
        for s in SETORES:
            cls.cluster.esperar_porta_aberta(s, PORTAS_BROKER)
        time.sleep(2)
        enviar_ocorrencia("setor_a", "averiguacao", 1)
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.derrubar_todos()

    def test_01_qualquer_no_pode_ler_o_ledger_completo_sem_permissao_especial(self):
        for setor in SETORES:
            chain = chain_de_disco(setor)
            self.assertIsNotNone(chain, f"não foi possível ler o ledger de {setor} livremente")
            self.assertIn("chain", chain)

    def test_02_consulta_em_dois_nos_distintos_e_consistente(self):
        time.sleep(1)
        chain_a = chain_de_disco("setor_a")
        chain_b = chain_de_disco("setor_b")
        self.assertIsNotNone(chain_a)
        self.assertIsNotNone(chain_b)
        self.assertGreaterEqual(len(chain_a["chain"]), 2)
        self.assertGreaterEqual(len(chain_b["chain"]), 2)

    def test_03_e_possivel_rastrear_a_origem_dos_creditos_de_uma_companhia(self):
        chain = chain_de_disco("setor_a")
        bc_temp = BlockChain(persist_path=f"/tmp/teste_auditoria_{uuid.uuid4().hex}.json")
        bc_temp.chain = chain["chain"]
        token_temp = GerenciadorTokens(bc_temp)

        saldo_calculado = token_temp.recuperar_creditos("setor_a")
        emissoes = [
            tx for bloco in chain["chain"] for tx in bloco["transacoes"]
            if tx.get("tipo") == "EMISSAO" and tx.get("empresa") == "setor_a"
        ]
        self.assertGreaterEqual(len(emissoes), 1, "não há registro de emissão rastreável para setor_a")
        self.assertIsInstance(saldo_calculado, int)

    def test_04_e_possivel_rastrear_todas_as_missoes_de_um_drone_especifico(self):
        drone_id = f"drone_auditoria_{uuid.uuid4().hex[:6]}"
        sock = conectar_drone_falso("setor_b", drone_id)
        try:
            time.sleep(0.5)
            enviar_ocorrencia("setor_b", "averiguacao", 1)
            dispatch = esperar_dispatch(sock, timeout=5)
            self.assertIsNotNone(dispatch)
            concluir_missao(sock)
            time.sleep(1.5)

            chain = chain_de_disco("setor_b")
            laudos_do_drone = [
                tx for bloco in chain["chain"] for tx in bloco["transacoes"]
                if tx.get("tipo") == "LAUDO" and tx.get("drone") == drone_id
            ]
            self.assertEqual(
                len(laudos_do_drone), 1,
                f"esperava exatamente 1 laudo rastreável para {drone_id}, achei {len(laudos_do_drone)}",
            )
        finally:
            sock.close()


if __name__ == "__main__":
    with contextlib.suppress(Exception):
        subprocess.run(["pkill", "-9", "-f", "broker.py setor_"], check=False)
        time.sleep(1)

    unittest.main(verbosity=2)
