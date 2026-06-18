import hmac
import hashlib

class GerenciadorAutenticacao:

    def __init__(self):
        self.chaves = {
            "setor_a": b"chave_do_setor_a",
            "setor_b": b"chave_do_setor_b",
            "setor_c": b"chave_do_setor_c"
        }

    def assinar(self, setor, dados):
        if setor not in self.chaves:
            raise ValueError(f"Setor desconhecido: {setor}")
        chave = self.chaves[setor]

        assinatura = hmac.new(chave, dados.encode(), hashlib.sha256 )

        return assinatura.hexdigest()

    def verificar(self, setor, dados, assinatura_recebida):

        if setor not in self.chaves:
            return False

        assinatura_esperada = self.assinar(
            setor,
            dados
        )

        return hmac.compare_digest(
            assinatura_esperada,
            assinatura_recebida
        )
