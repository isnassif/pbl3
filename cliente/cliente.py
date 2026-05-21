import socket
import json
import sys
import os
sys.stdout.reconfigure(line_buffering=True)

def _parse_addr(env_key, default_host, default_port):
    val = os.getenv(env_key)
    if val:
        host, port = val.rsplit(":", 1)
        return (host, int(port))
    return (default_host, default_port)

BROKERS_SENSORES = {
    "setor_a": _parse_addr("BROKER_A", "127.0.0.1", 7001),
    "setor_b": _parse_addr("BROKER_B", "127.0.0.1", 7002),
    "setor_c": _parse_addr("BROKER_C", "127.0.0.1", 7003),
}

TIPOS = {
    "1": ("averiguacao", 1),
    "2": ("possivel_ataque", 2),
    "3": ("ataque_concreto", 3),
}

if len(sys.argv) < 2:
    print("Uso: python cliente.py <setor_a|setor_b|setor_c>")
    sys.exit(1)

meu_setor = sys.argv[1]

print(f"\nCliente manual — setor: {meu_setor}")
print("─" * 40)
print("Tipos de ocorrência:")
print("  1 → averiguacao      (BAIXA)")
print("  2 → possivel_ataque  (MÉDIA)")
print("  3 → ataque_concreto  (ALTA)")
print("  q → sair")
print("─" * 40)

while True:
    try:
        escolha = input("\nDigite o tipo de ocorrência [1/2/3/q]: ").strip()

        if escolha == "q":
            print("Encerrando cliente.")
            break

        if escolha not in TIPOS:
            print("Opção inválida. Digite 1, 2, 3 ou q.")
            continue

        ocorrencia, prioridade = TIPOS[escolha]

        host, port = BROKERS_SENSORES[meu_setor]
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.settimeout(3)
        tcp_socket.connect((host, port))

        payload = json.dumps({
            "ocorrencia": ocorrencia,
            "prioridade": prioridade,
            "origem": meu_setor
        })

        tcp_socket.sendall(payload.encode())
        tcp_socket.close()

        print(f"✓ Enviado: {ocorrencia} | prioridade {prioridade}")

    except KeyboardInterrupt:
        print("\nEncerrando cliente.")
        break
    except Exception as e:
        print(f"Erro ao enviar: {e}")