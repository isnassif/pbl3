from blockchain.blockchain import BlockChain
import threading



class GerenciadorTokens:

    def __init__(self,blockchain):
        self.saldos = {
            'setor_a': 0,
            'setor_b': 0,
            'setor_c': 0
        }
        self.lock_token = threading.Lock()
        self.blockchain = blockchain

    def gastar(self, empresa, valor, ocorrencia, req_id):

        if empresa not in self.saldos:
            return False

        with self.lock_token:

            if valor <= self.consultar_saldo(empresa):

                self.saldos[empresa] -= valor

                transacao = {
                    'tipo': 'PAGAMENTO',
                    'valor': valor,
                    'empresa': empresa,
                    'ocorrencia': ocorrencia,
                    'req_id': req_id
                }

                self.blockchain.adicionar_transacao(transacao)

                return True

            return False

    def consultar_saldo(self, empresa):
        return self.saldos.get(empresa, 0)

    def emitir_creditos(self, empresa, valor):

        if empresa not in self.saldos:
            return False

        self.saldos[empresa] += valor

        transacao = {
            'tipo': 'EMISSAO',
            'valor': valor,
            'empresa': empresa
        }
        self.blockchain.adicionar_transacao(transacao)

        return True

    def recuperar_creditos(self, empresa):

        valor_final = 0

        for bloco in self.blockchain.chain:
            for transacao in bloco['transacoes']:

                if (
                    transacao['empresa'] == empresa
                    and transacao['tipo'] == 'EMISSAO'
                ):
                    valor_final += transacao['valor']

                elif (
                    transacao['empresa'] == empresa
                    and transacao['tipo'] == 'PAGAMENTO'
                ):
                    valor_final -= transacao['valor']

        return valor_final
    
    def inicializar_saldos(self):
        self.emitir_creditos("setor_a", 100)
        self.emitir_creditos("setor_b", 100)
        self.emitir_creditos("setor_c", 100)
    
    def recalcular_saldos(self):
        na=self.recuperar_creditos("setor_a")
        nb=self.recuperar_creditos("setor_b")
        nc=self.recuperar_creditos("setor_c")

        self.saldos["setor_a"] = na
        self.saldos["setor_b"] = nb
        self.saldos["setor_c"] = nc



