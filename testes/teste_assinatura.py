"""
TESTE 4 — AUTENTICAÇÃO DE MENSAGENS (ASSINATURA HMAC)

Valida se o GerenciadorAutenticacao bloqueia corretamente tentativas
de um setor se passar por outro (fraude de identidade) e se mensagens
legítimas continuam sendo aceitas.

Parte 1 — testes ISOLADOS (sem rede): chamam GerenciadorAutenticacao
          diretamente, simulando os mesmos cenários que o broker
          enfrenta ao verificar uma mensagem.

Parte 2 — teste de REDE (opcional): dispara mensagens reais para um
          broker em execução, com origem falsificada, e confirma que
          ele rejeita a transação no log (não dá pra "ver" o retorno
          aqui — o teste só envia e você confere no terminal do broker
          se apareceu "ASSINATURA INVÁLIDA").

Uso:
    python teste_assinatura.py            → roda só os testes isolados
    python teste_assinatura.py --rede     → roda isolados + ataque de rede
"""

import sys
import os
import json
import socket

# permite importar blockchain.assinatura mesmo estando fora da pasta broker/
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "broker"))
from blockchain.assinatura import GerenciadorAutenticacao

BROKERS_SENSORES = {
    "setor_a": ("127.0.0.1", 7001),
    "setor_b": ("127.0.0.1", 7002),
    "setor_c": ("127.0.0.1", 7003),
}


def cabecalho(titulo):
    print()
    print(f"  ╔{'═'*60}╗")
    print(f"  ║ {titulo:^58} ║")
    print(f"  ╚{'═'*60}╝")


def resultado(nome, passou):
    status = "✅ PASSOU" if passou else "❌ FALHOU"
    print(f"  [{status}] {nome}")
    return passou


# ─── PARTE 1 — TESTES ISOLADOS ─────────────────────────────────────────────

def teste_assinatura_valida(auth):
    """Setor assina e verifica sua própria mensagem — deve aceitar."""
    dados = "setor_a:ataque_concreto:3"
    assinatura = auth.assinar("setor_a", dados)
    ok = auth.verificar("setor_a", dados, assinatura)
    return resultado("assinatura válida é aceita", ok is True)


def teste_falsificacao_de_origem(auth):
    """
    setor_b assina como ele mesmo, mas o broker (vítima) reconstrói
    os dados acreditando que a origem é setor_a. A verificação deve
    falhar, porque setor_b não conhece a chave de setor_a.
    """
    dados_reais = "setor_b:ataque_concreto:3"
    assinatura_de_b = auth.assinar("setor_b", dados_reais)

    # broker confia no campo "origem" da mensagem, que está mentindo
    dados_que_o_broker_reconstrói = "setor_a:ataque_concreto:3"
    aceito = auth.verificar("setor_a", dados_que_o_broker_reconstrói, assinatura_de_b)

    return resultado("fraude de identidade (setor_b finge ser setor_a) é rejeitada", aceito is False)


def teste_assinatura_corrompida(auth):
    """Assinatura válida, mas alterada em 1 caractere — deve rejeitar."""
    dados = "setor_c:averiguacao:1"
    assinatura = auth.assinar("setor_c", dados)
    assinatura_corrompida = assinatura[:-1] + ("0" if assinatura[-1] != "0" else "1")
    aceito = auth.verificar("setor_c", dados, assinatura_corrompida)
    return resultado("assinatura corrompida é rejeitada", aceito is False)


def teste_dados_alterados_apos_assinar(auth):
    """
    Mensagem assinada para uma prioridade, mas o atacante muda a
    prioridade depois de capturar a assinatura (replay com alteração).
    """
    dados_originais = "setor_a:averiguacao:1"
    assinatura = auth.assinar("setor_a", dados_originais)

    dados_alterados = "setor_a:ataque_concreto:3"  # tentando subir a prioridade
    aceito = auth.verificar("setor_a", dados_alterados, assinatura)
    return resultado("alteração do conteúdo após assinatura é rejeitada", aceito is False)


def teste_setor_inexistente(auth):
    """Setor que não está cadastrado nas chaves nunca deve verificar com sucesso."""
    dados = "setor_fantasma:ataque_concreto:3"
    aceito = auth.verificar("setor_fantasma", dados, "qualquer_coisa")
    return resultado("setor desconhecido é rejeitado", aceito is False)


def rodar_testes_isolados():
    cabecalho("PARTE 1 — TESTES ISOLADOS (GerenciadorAutenticacao)")
    auth = GerenciadorAutenticacao()

    testes = [
        teste_assinatura_valida,
        teste_falsificacao_de_origem,
        teste_assinatura_corrompida,
        teste_dados_alterados_apos_assinar,
        teste_setor_inexistente,
    ]

    resultados = [t(auth) for t in testes]

    print()
    total = len(resultados)
    passou = sum(resultados)
    print(f"  {passou}/{total} testes isolados passaram")
    return passou == total


# ─── PARTE 2 — ATAQUE REAL VIA REDE ────────────────────────────────────────

def enviar_ocorrencia(setor_destino, payload):
    host, port = BROKERS_SENSORES[setor_destino]
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        sock.sendall(json.dumps(payload).encode())
        sock.close()
        return True
    except Exception as e:
        print(f"  ⚠ falha ao conectar em {setor_destino}: {e}")
        return False


def ataque_falsificacao_de_origem(auth):
    """
    Simula setor_b mandando uma ocorrência para o PRÓPRIO broker dele,
    mas se identificando como setor_a no campo 'origem' — tentando
    gastar créditos do setor_a sem autorização.

    Resultado esperado: o broker do setor_b deve logar
    "ASSINATURA INVÁLIDA" e recusar a operação, sem descontar nada
    do saldo de setor_a.
    """
    cabecalho("PARTE 2 — ATAQUE REAL VIA REDE")
    print("  Disparando mensagem para setor_b, fingindo ser setor_a...")
    print("  Confira no terminal do broker setor_b se aparece:")
    print("  '⚠ ASSINATURA INVÁLIDA — pagamento de setor_a rejeitado'")
    print()

    ocorrencia = "ataque_concreto"
    prioridade = 3

    # o atacante (setor_b) só consegue assinar como setor_b,
    # mesmo querendo se passar por setor_a
    dados_assinados_de_verdade = f"setor_b:{ocorrencia}:{prioridade}"
    assinatura_falsa = auth.assinar("setor_b", dados_assinados_de_verdade)

    payload_malicioso = {
        "ocorrencia": ocorrencia,
        "prioridade": prioridade,
        "origem": "setor_a",          # mentira no campo origem
        "assinatura": assinatura_falsa
    }

    enviado = enviar_ocorrencia("setor_b", payload_malicioso)
    if enviado:
        print("  ✅ payload malicioso enviado — verifique o log do broker setor_b")
    else:
        print("  ❌ não foi possível enviar — broker setor_b está rodando?")


def ataque_mensagem_legitima(auth):
    """Envia uma ocorrência legítima para confirmar que mensagens
    corretas continuam funcionando normalmente após os testes de ataque."""
    print()
    print("  Disparando mensagem LEGÍTIMA de setor_c para comparação...")

    ocorrencia = "averiguacao"
    prioridade = 1
    dados = f"setor_c:{ocorrencia}:{prioridade}"
    assinatura = auth.assinar("setor_c", dados)

    payload_legitimo = {
        "ocorrencia": ocorrencia,
        "prioridade": prioridade,
        "origem": "setor_c",
        "assinatura": assinatura
    }

    enviado = enviar_ocorrencia("setor_c", payload_legitimo)
    if enviado:
        print("  ✅ mensagem legítima enviada — deve aparecer 'CRÉDITO OK' no log do setor_c")


if __name__ == "__main__":
    isolados_ok = rodar_testes_isolados()

    if "--rede" in sys.argv:
        auth = GerenciadorAutenticacao()
        ataque_falsificacao_de_origem(auth)
        ataque_mensagem_legitima(auth)
    else:
        print()
        print("  (rode com --rede para também testar contra brokers reais em execução)")

    print()
    if isolados_ok:
        print("  ✅ Todos os testes isolados passaram.")
    else:
        print("  ❌ Algum teste isolado falhou — revise GerenciadorAutenticacao.")
