from blockchain.blockchain import BlockChain

class GerenciadorTokens:

    def __init__(self,blockchain):
        self.saldos = {
            'setor_a': 0,
            'setor_b': 0,
            'setor_c': 0
        }

        self.blockchain = blockchain

    def gastar(self, empresa, valor, ocorrencia,req_id):

        if empresa not in self.saldos:
            return False

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
    




bc = BlockChain()

token = GerenciadorTokens(bc)

token.emitir_creditos("empresa A", 100)

print(token.consultar_saldo("empresa A"))