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
        
    def transferir(self, origem, destino, valor):
        if origem not in self.saldos or destino not in self.saldos:
            return False
        with self.lock_token:
            if valor <= 0 or valor > self.consultar_saldo(origem):
                return False
            self.saldos[origem] -= valor
            self.saldos[destino] += valor
            self.blockchain.adicionar_transacao({
                'tipo': 'TRANSFERENCIA',
                'valor': valor,
                'de': origem,
                'para': destino
            })
            return True
    

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
                tipo = transacao.get('tipo')

                if tipo == 'EMISSAO' and transacao.get('empresa') == empresa:
                    valor_final += transacao['valor']

                elif tipo == 'PAGAMENTO' and transacao.get('empresa') == empresa:
                    valor_final -= transacao['valor']

                elif tipo == 'TRANSFERENCIA':
                    if transacao.get('de') == empresa:
                        valor_final -= transacao['valor']
                    if transacao.get('para') == empresa:
                        valor_final += transacao['valor']

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



