"""
TESTE 3 — FALHAS CRÍTICAS
Menu interativo para simular condições críticas e verificar
o comportamento do sistema sob falhas.

Cenários disponíveis:
  1. Rajada de requisições concorrentes (todas ao mesmo tempo)
  2. Requisições durante reconexão de broker
  3. Verificação de recuperação de requisição após queda de drone
  4. Requisições simultâneas de todos os setores (stress)

Uso:
    python teste_falhas.py
"""

import socket
import json
import threading
import time
import random
import sys

BROKERS_SENSORES = {
    "setor_a": ("127.0.0.1", 7001),
    "setor_b": ("127.0.0.1", 7002),
    "setor_c": ("127.0.0.1", 7003),
}

TIPOS = {
    1: "averiguacao",
    2: "possivel_ataque",
    3: "ataque_concreto"
}

PRIORIDADE_LABEL = {1: "BAIXA", 2: "MÉDIA", 3: "ALTA"}
enviadas_ok = 0
enviadas_err = 0
lock_contador = threading.Lock()


def enviar(setor, ocorrencia, prioridade, label=""):
    global enviadas_ok, enviadas_err
    try:
        host, porta = BROKERS_SENSORES[setor]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, porta))
        payload = json.dumps({
            "ocorrencia": ocorrencia,
            "prioridade": prioridade,
            "origem": setor
        })
        sock.sendall(payload.encode())
        sock.close()
        with lock_contador:
            enviadas_ok += 1
        if label:
            print(f"  ✓ {label}  {setor:<8}  {ocorrencia:<20}  P{prioridade} {PRIORIDADE_LABEL[prioridade]}")
    except Exception as e:
        with lock_contador:
            enviadas_err += 1
        if label:
            print(f"  ✗ {label}  {setor:<8}  ERRO: {e}")


def cenario_rajada_concorrente():
    """
    Envia todas as requisições exatamente ao mesmo tempo (sem delay).
    Testa se o Ricart-Agrawala garante exclusão mútua sob alta concorrência.
    """
    global enviadas_ok, enviadas_err
    enviadas_ok = 0
    enviadas_err = 0

    try:
        n = int(input("  Quantas requisições simultâneas? "))
    except ValueError:
        print("  Valor inválido.")
        return

    setores = list(BROKERS_SENSORES.keys())
    threads = []

    print(f"\n  Disparando {n} requisições ao mesmo tempo...")
    inicio = time.time()

    for i in range(n):
        prioridade = random.randint(1, 3)
        setor = random.choice(setores)
        t = threading.Thread(
            target=enviar,
            args=(setor, TIPOS[prioridade], prioridade, f"[{i+1:>3}]")
        )
        threads.append(t)

    # Inicia todas ao mesmo tempo
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    fim = time.time()
    print(f"\n  Concluído em {fim - inicio:.2f}s")
    print(f"  ✓ Enviadas com sucesso : {enviadas_ok}")
    print(f"  ✗ Falhas               : {enviadas_err}")
    print()
    print("  Verifique nos brokers se:")
    print("  → A fila tem exatamente os itens enviados com sucesso")
    print("  → A ordem respeita a prioridade (P3 > P2 > P1)")
    print("  → Todos os brokers mostram a mesma fila")


def cenario_durante_reconexao():
    """
    Envia requisições enquanto aguarda o operador reconectar um broker manualmente.
    Verifica se o broker que voltou absorve a fila corretamente.
    """
    try:
        n = int(input("  Quantas requisições enviar enquanto broker está offline? "))
    except ValueError:
        print("  Valor inválido.")
        return

    setor_alvo = input("  Qual broker vai derrubar? (setor_a/setor_b/setor_c): ").strip()
    if setor_alvo not in BROKERS_SENSORES:
        print("  Setor inválido.")
        return

    outros = [s for s in BROKERS_SENSORES if s != setor_alvo]
    print(f"\n  ⚠  DERRUBE O BROKER {setor_alvo.upper()} AGORA (Ctrl+C no terminal dele)")
    input("  Pressione Enter quando o broker estiver offline...")

    print(f"\n  Enviando {n} requisições pelos outros setores...")
    threads = []
    for i in range(n):
        prioridade = random.randint(1, 3)
        setor = random.choice(outros)
        delay = random.uniform(0, 2.0)
        t = threading.Thread(
            target=enviar,
            args=(setor, TIPOS[prioridade], prioridade, f"[{i+1:>3}]")
        )
        threads.append(t)
        t.start()
        time.sleep(0.1)

    for t in threads:
        t.join()

    print(f"\n  {n} requisições enviadas com o broker offline.")
    print(f"\n  ⚠  REACTIVE O BROKER {setor_alvo.upper()} AGORA")
    input("  Pressione Enter quando o broker estiver de volta online...")

    print("  Aguardando sync inicial do broker reativado (10s)...")
    time.sleep(10)

    print()
    print("  Verifique no terminal do broker reativado se:")
    print(f"  → Ele exibiu 'SYNC RECEBIDA' com as {n} requisições")
    print(f"  → A fila dele é igual à dos brokers que ficaram online")
    print("  → A ordem respeita a prioridade")


def cenario_queda_drone():
    """
    Guia o operador a derrubar um drone durante missão
    e verificar se a requisição volta à fila.
    """
    print()
    print("  INSTRUÇÕES:")
    print("  1. Certifique-se que há pelo menos 1 drone conectado")
    print("  2. Enviaremos 1 requisição de alta prioridade")
    print("  3. Assim que o drone aceitar a missão, você dá Ctrl+C nele")
    print("  4. Verificamos se a requisição voltou à fila")
    print()
    input("  Pressione Enter para enviar a requisição de ataque_concreto (P3)...")

    setor = random.choice(list(BROKERS_SENSORES.keys()))
    enviar(setor, "ataque_concreto", 3, "[REQ]")

    print(f"\n  Requisição enviada ao {setor}.")
    print("  Observe o terminal do broker — quando aparecer 'DRONE X → em missão'")
    print("  DERRUBE O DRONE imediatamente com Ctrl+C no terminal dele.")
    print()
    input("  Pressione Enter após derrubar o drone...")

    print()
    print("  Verifique no broker se apareceu:")
    print("  → '⚠  DRONE CAIU DURANTE MISSÃO'")
    print("  → 'RECUPERAÇÃO — ataque_concreto voltou à fila'")
    print("  → A fila mostra a requisição de volta no topo")
    resultado = input("\n  A requisição voltou à fila? (s/n): ").strip().lower()
    if resultado == "s":
        print("  ✅ TESTE PASSOU — recuperação de drone funcionou corretamente.")
    else:
        print("  ❌ TESTE FALHOU — requisição não foi recuperada.")


def cenario_stress():
    """
    Envia requisições de todos os setores simultaneamente em várias ondas.
    Testa o sistema sob carga máxima contínua.
    """
    try:
        ondas = int(input("  Quantas ondas? "))
        por_onda = int(input("  Requisições por onda? "))
        intervalo = float(input("  Intervalo entre ondas (segundos)? "))
    except ValueError:
        print("  Valores inválidos.")
        return

    global enviadas_ok, enviadas_err
    enviadas_ok = 0
    enviadas_err = 0

    setores = list(BROKERS_SENSORES.keys())
    inicio = time.time()

    print(f"\n  Iniciando {ondas} ondas de {por_onda} requisições cada...")
    print()

    for onda in range(1, ondas + 1):
        print(f"  --- ONDA {onda}/{ondas} ---")
        threads = []
        for i in range(por_onda):
            prioridade = random.randint(1, 3)
            setor = random.choice(setores)
            t = threading.Thread(
                target=enviar,
                args=(setor, TIPOS[prioridade], prioridade, "")
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        print(f"  Onda {onda} concluída — {por_onda} requisições disparadas")
        if onda < ondas:
            time.sleep(intervalo)

    fim = time.time()
    total = ondas * por_onda
    print()
    print(f"  Stress test concluído em {fim - inicio:.2f}s")
    print(f"  Total disparado      : {total}")
    print(f"  ✓ Enviadas com sucesso: {enviadas_ok}")
    print(f"  ✗ Falhas              : {enviadas_err}")
    print()
    print("  Verifique nos brokers se:")
    print(f"  → A fila tem {enviadas_ok} itens")
    print("  → Todos os brokers têm a mesma fila")
    print("  → A ordem é consistente com as prioridades")


def menu():
    while True:
        print()
        print("╔══════════════════════════════════════════════╗")
        print("║         TESTES DE FALHAS CRÍTICAS            ║")
        print("╠══════════════════════════════════════════════╣")
        print("║  1. Rajada concorrente (exclusão mútua)      ║")
        print("║  2. Requisições durante reconexão de broker  ║")
        print("║  3. Queda de drone durante missão            ║")
        print("║  4. Stress test (múltiplas ondas)            ║")
        print("║  0. Sair                                     ║")
        print("╚══════════════════════════════════════════════╝")
        opcao = input("  Escolha: ").strip()

        if opcao == "1":
            cenario_rajada_concorrente()
        elif opcao == "2":
            cenario_durante_reconexao()
        elif opcao == "3":
            cenario_queda_drone()
        elif opcao == "4":
            cenario_stress()
        elif opcao == "0":
            print("  Encerrando testes.")
            break
        else:
            print("  Opção inválida.")


if __name__ == "__main__":
    menu()