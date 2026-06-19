"""
TESTE 5 — PREVENÇÃO DE DUPLO GASTO (MENU INTERATIVO)

Menu para escolher qual teste rodar e configurar parâmetros na hora
(setor alvo, prioridade, número de requisições), em vez de rodar tudo
de uma vez com valores fixos.

Pré-requisitos: os 3 brokers precisam estar rodando.
    python broker.py setor_a
    python broker.py setor_b
    python broker.py setor_c

Uso:
    python teste_duplo_gasto.py
"""

import sys
import os
import json
import socket
import threading
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "broker"))
from blockchain.assinatura import GerenciadorAutenticacao

BROKERS_SENSORES = {
    "setor_a": ("127.0.0.1", 7001),
    "setor_b": ("127.0.0.1", 7002),
    "setor_c": ("127.0.0.1", 7003),
}

CUSTO_POR_PRIORIDADE = {1: 2, 2: 5, 3: 10}
NOME_PRIORIDADE = {1: "BAIXA", 2: "MÉDIA", 3: "ALTA"}
OCORRENCIA_POR_PRIORIDADE = {1: "averiguacao", 2: "possivel_ataque", 3: "ataque_concreto"}

auth = GerenciadorAutenticacao()


# ─── UTILITÁRIOS DE INTERFACE ──────────────────────────────────────────────

def cabecalho(titulo):
    print()
    print(f"  ╔{'═'*64}╗")
    print(f"  ║ {titulo:^62} ║")
    print(f"  ╚{'═'*64}╝")


def perguntar_setor(rotulo="Setor alvo", default="setor_a"):
    print(f"  {rotulo} [{', '.join(BROKERS_SENSORES)}] (enter = {default}): ", end="")
    resp = input().strip()
    return resp if resp in BROKERS_SENSORES else default


def perguntar_inteiro(rotulo, default, minimo=1, maximo=10_000):
    print(f"  {rotulo} (enter = {default}): ", end="")
    resp = input().strip()
    if not resp:
        return default
    try:
        valor = int(resp)
        return max(minimo, min(maximo, valor))
    except ValueError:
        print(f"  valor inválido, usando padrão ({default})")
        return default


def perguntar_prioridade(default=3):
    print(f"  Prioridade [1=BAIXA  2=MÉDIA  3=ALTA] (enter = {default}): ", end="")
    resp = input().strip()
    if resp in ("1", "2", "3"):
        return int(resp)
    return default


# ─── ENVIO ──────────────────────────────────────────────────────────────────

def montar_payload(origem, ocorrencia, prioridade):
    dados = f"{origem}:{ocorrencia}:{prioridade}"
    assinatura = auth.assinar(origem, dados)
    return json.dumps({
        "ocorrencia": ocorrencia,
        "prioridade": prioridade,
        "origem": origem,
        "assinatura": assinatura
    })


def disparar(setor_destino, payload, resultados, indice):
    host, port = BROKERS_SENSORES[setor_destino]
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        sock.sendall(payload.encode())
        sock.close()
        resultados[indice] = "enviado"
    except Exception as e:
        resultados[indice] = f"falha: {e}"


# ─── OPÇÃO 1 — N requisições simultâneas no mesmo broker ──────────────────

def opcao_mesmo_broker():
    cabecalho("N REQUISIÇÕES SIMULTÂNEAS NO MESMO BROKER")
    setor = perguntar_setor("Setor que vai receber as requisições")
    prioridade = perguntar_prioridade()
    n = perguntar_inteiro("Quantas requisições simultâneas disparar?", default=2, minimo=2, maximo=200)

    custo = CUSTO_POR_PRIORIDADE[prioridade]
    print()
    print(f"  Setor alvo   : {setor}")
    print(f"  Custo/req    : {custo} créditos (prioridade {prioridade}/{NOME_PRIORIDADE[prioridade]})")
    print(f"  Requisições  : {n} disparadas ao mesmo tempo")
    print(f"  Custo total  : {custo * n} créditos (se TODAS passassem)")
    print()
    print("  Disparando...")

    resultados = [None] * n
    threads = [
        threading.Thread(
            target=disparar,
            args=(setor, montar_payload(setor, OCORRENCIA_POR_PRIORIDADE[prioridade], prioridade), resultados, i)
        )
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    enviados = sum(1 for r in resultados if r == "enviado")
    print(f"  {enviados}/{n} mensagens entregues ao broker")
    print()
    print(f"  ⚠ Verifique no terminal do broker '{setor}':")
    print(f"    - quantas vezes apareceu 'CRÉDITO OK' (deve ser limitado pelo saldo)")
    print(f"    - se apareceu 'CRÉDITO NEGADO' para as excedentes")
    print(f"    - o saldo final NUNCA pode ter sido descontado mais vezes do que")
    print(f"      o saldo disponível permitia, mesmo todas chegando juntas")


# ─── OPÇÃO 2 — mesma empresa, brokers diferentes ───────────────────────────

def opcao_entre_brokers():
    cabecalho("MESMA EMPRESA, REQUISIÇÕES EM BROKERS DIFERENTES")
    setor_vitima = perguntar_setor("Empresa/setor que terá o saldo testado")
    prioridade = perguntar_prioridade()

    outros = [b for b in BROKERS_SENSORES if b != setor_vitima]
    print(f"  Requisição 1 será enviada para: {outros[0]}")
    print(f"  Requisição 2 será enviada para: {setor_vitima}")
    print()
    print("  Disparando...")

    ocorrencia = OCORRENCIA_POR_PRIORIDADE[prioridade]
    resultados = [None, None]
    payload_1 = montar_payload(setor_vitima, ocorrencia, prioridade)
    payload_2 = montar_payload(setor_vitima, ocorrencia, prioridade)

    t1 = threading.Thread(target=disparar, args=(outros[0], payload_1, resultados, 0))
    t2 = threading.Thread(target=disparar, args=(setor_vitima, payload_2, resultados, 1))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print(f"    requisição → {outros[0]}: {resultados[0]}")
    print(f"    requisição → {setor_vitima}: {resultados[1]}")
    print()
    print(f"  ⚠ Aguarde alguns segundos para a propagação de blocos (BLOCK_NEW)")
    print(f"  e então compare o saldo de '{setor_vitima}' em AMBOS os brokers —")
    print(f"  devem ficar IGUAIS após sincronizar, sem cobrar duas vezes por engano.")


# ─── OPÇÃO 3 — transação afeta SÓ o saldo do setor indicado ────────────────

def opcao_isolamento_de_saldo():
    cabecalho("TRANSAÇÃO AFETA APENAS O SALDO DO SETOR INDICADO")
    setor_alvo = perguntar_setor("Setor que vai gastar crédito")
    prioridade = perguntar_prioridade()
    outros = [b for b in BROKERS_SENSORES if b != setor_alvo]

    print()
    print(f"  Setor que vai gastar : {setor_alvo}")
    print(f"  Setores que NÃO devem ser afetados: {', '.join(outros)}")
    print()
    print("  📋 Roteiro deste teste:")
    print(f"     1. Anote AGORA o saldo de TODOS os setores")
    print(f"        (use o '_mostrar_blockchain()' ou olhe o log de cada broker)")
    print(f"     2. Pressione enter aqui para disparar UMA requisição de {setor_alvo}")
    print(f"     3. Depois, confira de novo o saldo dos 3 setores")
    print(f"     4. Esperado: só {setor_alvo} teve o saldo reduzido;")
    print(f"        {', '.join(outros)} devem continuar EXATAMENTE com o mesmo valor")
    print()
    input("  Pressione enter para disparar a requisição...")

    ocorrencia = OCORRENCIA_POR_PRIORIDADE[prioridade]
    payload = montar_payload(setor_alvo, ocorrencia, prioridade)
    resultados = [None]
    disparar(setor_alvo, payload, resultados, 0)

    print(f"  requisição → {setor_alvo}: {resultados[0]}")
    print()
    print(f"  ⚠ Agora confira o saldo dos 3 setores de novo.")
    print(f"  Custo esperado para {setor_alvo}: {CUSTO_POR_PRIORIDADE[prioridade]} créditos")
    print(f"  Custo esperado para {', '.join(outros)}: 0 (inalterado)")


# ─── MENU ───────────────────────────────────────────────────────────────────

OPCOES = {
    "1": ("N requisições simultâneas no MESMO broker", opcao_mesmo_broker),
    "2": ("Mesma empresa, requisições em brokers DIFERENTES", opcao_entre_brokers),
    "3": ("Confirmar que a transação só afeta o saldo do setor indicado", opcao_isolamento_de_saldo),
}


def menu():
    while True:
        cabecalho("TESTE DE PREVENÇÃO DE DUPLO GASTO")
        for chave, (descricao, _) in OPCOES.items():
            print(f"  [{chave}] {descricao}")
        print(f"  [0] Sair")
        print()
        escolha = input("  Escolha uma opção: ").strip()

        if escolha == "0":
            print("  até mais!")
            break
        elif escolha in OPCOES:
            _, funcao = OPCOES[escolha]
            funcao()
            print()
            input("  Pressione enter para voltar ao menu...")
        else:
            print("  opção inválida")


if __name__ == "__main__":
    menu()
