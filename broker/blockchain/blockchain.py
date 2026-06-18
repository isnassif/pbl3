import datetime
import hashlib
import json
import os
import threading


# Em Docker: /data existe como volume montado.
# Local: salva numa pasta 'data/' ao lado do broker.py
_BASE_DIR = "/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CHAIN_FILE_DEFAULT = os.path.join(_BASE_DIR, "blockchain.json")


class BlockChain:
    def __init__(self, persist_path: str = CHAIN_FILE_DEFAULT):
        self.chain = []
        self.transacoes_pendentes = []
        self.persist_path = persist_path
        self._lock_persist = threading.Lock()
        # Genesis NÃO é minerado aqui.
        # O broker chama criar_genesis() após o GerenciadorToken
        # adicionar as transações de EMISSAO iniciais.

    # ─── PERSISTÊNCIA ─────────────────────────────────────────────────────────

    def carregar_do_disco(self) -> bool:
        """Tenta carregar a chain salva em disco.
        Retorna True se carregou com sucesso e a chain é válida."""
        if not os.path.exists(self.persist_path):
            return False
        try:
            with open(self.persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            chain = data.get("chain", [])
            if chain and self.chain_valid(chain):
                self.chain = chain
                print(f"[blockchain] ✅ chain restaurada do disco — {len(chain)} blocos")
                return True
            else:
                print(f"[blockchain] ⚠  arquivo encontrado mas chain inválida — ignorado")
                return False
        except Exception as e:
            print(f"[blockchain] ⚠  erro ao carregar {self.persist_path}: {e}")
            return False

    def salvar_no_disco(self):
        """Serializa a chain inteira para o arquivo de persistência."""
        with self._lock_persist:
            try:
                os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
                tmp = self.persist_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"chain": self.chain}, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.persist_path)  # atomic write
            except Exception as e:
                print(f"[blockchain] ⚠  erro ao salvar {self.persist_path}: {e}")

    # ─── CORE ─────────────────────────────────────────────────────────────────

    def criar_genesis(self):
        """Minera o bloco genesis com as emissões iniciais já adicionadas."""
        bloco = self.create_block(proof=1, previous_hash='0')
        return bloco

    def create_block(self, proof, previous_hash):
        block = {
            'index': len(self.chain) + 1,
            'timestamp': str(datetime.datetime.now()),
            'proof': proof,
            'previous_hash': previous_hash,
            'transacoes': self.transacoes_pendentes.copy()
        }
        self.transacoes_pendentes = []
        self.chain.append(block)
        self.salvar_no_disco()
        return block

    def print_previous_block(self):
        return self.chain[-1]

    def adicionar_transacao(self, transacao):
        self.transacoes_pendentes.append(transacao)

    def proof_of_work(self, previous_proof):
        new_proof = 1
        check_proof = False
        while check_proof is False:
            hash_operation = hashlib.sha256(
                str(new_proof ** 2 - previous_proof ** 2).encode()
            ).hexdigest()
            if hash_operation[:4] == '0000':
                check_proof = True
            else:
                new_proof += 1
        return new_proof

    def hash(self, block):
        encoded_block = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(encoded_block).hexdigest()

    def chain_valid(self, chain):
        previous_block = chain[0]
        block_index = 1
        while block_index < len(chain):
            block = chain[block_index]
            if block['previous_hash'] != self.hash(previous_block):
                return False
            previous_proof = previous_block['proof']
            proof = block['proof']
            hash_operation = hashlib.sha256(
                str(proof ** 2 - previous_proof ** 2).encode()
            ).hexdigest()
            if hash_operation[:4] != '0000':
                return False
            previous_block = block
            block_index += 1
        return True
