"""
TESTE 6 — SETOR MALICIOSO, CONSENSO POR MAIORIA E RESILIÊNCIA A QUEDAS
(MENU INTERATIVO)

Este arquivo MANIPULA DIRETAMENTE os arquivos {setor}_blockchain.json
em disco, simulando uma invasão real (alguém editando o arquivo "por
fora", sem passar pelo código Python) — e também te guia em cenários
que exigem você derrubar/subir brokers manualmente nos terminais.

Pré-requisitos: os 3 brokers precisam estar rodando há pelo menos
~20s (para terem 2+ blocos cada antes de adulterar).
    python broker.py setor_a
    python broker.py setor_b
    python broker.py setor_c

Uso:
    python teste_setor_malicioso.py
"""

import sys
import os
import json
import time
import socket

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "broker"))
from blockchain.assinatura import GerenciadorAutenticacao

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

ARQUIVOS = {
    "setor_a": os.path.join(BASE_DIR, "setor_a_blockchain.json"),
    "setor_b": os.path.join(BASE_DIR, "setor_b_blockchain.json"),
    "setor_c": os.path.join(BASE_DIR, "setor_c_blockchain.json"),
}

BROKERS_SENSORES = {
    "setor_a": ("127.0.0.1", 7001),
    "setor_b": ("127.0.0.1", 7002),
    "setor_c": ("127.0.0.1", 7003),
}

CUSTO_POR_PRIORIDADE = {1: 2, 2: 5, 3: 10}
OCORRENCIA_POR_PRIORIDADE = {1: "averiguacao", 2: "possivel_ataque", 3: "ataque_concreto"}

auth = GerenciadorAutenticacao()


# ─── UTILITÁRIOS DE INTERFACE ──────────────────────────────────────────────

def cabecalho(titulo):
    print()
    print(f"  ╔{'═'*64}╗")
    print(f"  ║ {titulo:^62} ║")
    print(f"  ╚{'═'*64}╝")


def perguntar_setor(rotulo="Setor alvo", default="setor_a"):
    print(f"  {rotulo} [{', '.join(ARQUIVOS)}] (enter = {default}): ", end="")
    resp = input().strip()
    return resp if resp in ARQUIVOS else default


def perguntar_setores_multiplos(rotulo):
    print(f"  {rotulo}")
    print(f"  Setores disponíveis: {', '.join(ARQUIVOS)}")
    print(f"  Digite separado por vírgula (ex.: setor_a,setor_b): ", end="")
    resp = input().strip()
    setores = [s.strip() for s in resp.split(",") if s.strip() in ARQUIVOS]
    return setores


def perguntar_inteiro(rotulo, default, minimo=1, maximo=999):
    print(f"  {rotulo} (enter = {default}): ", end="")
    resp = input().strip()
    if not resp:
        return default
    try:
        return max(minimo, min(maximo, int(resp)))
    except ValueError:
        return default


def perguntar_prioridade(default=3):
    print(f"  Prioridade [1=BAIXA  2=MÉDIA  3=ALTA] (enter = {default}): ", end="")
    resp = input().strip()
    if resp in ("1", "2", "3"):
        return int(resp)
    return default


# ─── MANIPULAÇÃO DE ARQUIVO (simula invasão) ───────────────────────────────

def carregar(setor):
    with open(ARQUIVOS[setor], "r", encoding="utf-8") as f:
        return json.load(f)


def salvar(setor, dados):
    with open(ARQUIVOS[setor], "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def fazer_backup(setores):
    for setor in setores:
        origem = ARQUIVOS[setor]
        destino = origem + ".backup"
        with open(origem, "r", encoding="utf-8") as f:
            conteudo = f.read()
        with open(destino, "w", encoding="utf-8") as f:
            f.write(conteudo)
    print(f"  💾 backup salvo para: {', '.join(setores)}")


def restaurar_backups(setores=None):
    alvos = setores if setores else list(ARQUIVOS.keys())
    for setor in alvos:
        backup = ARQUIVOS[setor] + ".backup"
        if os.path.exists(backup):
            with open(backup, "r", encoding="utf-8") as f:
                conteudo = f.read()
            with open(ARQUIVOS[setor], "w", encoding="utf-8") as f:
                f.write(conteudo)
            os.remove(backup)
            print(f"  ↩ {setor}: restaurado a partir do backup")
        else:
            print(f"  - {setor}: nenhum backup encontrado")


def adulterar(setor, valor_falso):
    """Altera o valor de uma transação já existente, sem recalcular
    hash — simula edição manual feita 'por fora' do sistema."""
    dados = carregar(setor)
    chain = dados["chain"]

    bloco_alvo = None
    tx_alvo = None
    for bloco in chain:
        for tx in bloco.get("transacoes", []):
            if "valor" in tx:
                bloco_alvo = bloco
                tx_alvo = tx
                break
        if tx_alvo:
            break

    if not tx_alvo:
        print(f"  ⚠ {setor}: nenhuma transação com 'valor' encontrada para adulterar")
        print(f"    (deixe o sistema rodar mais um pouco para gerar pagamentos/laudos)")
        return False

    valor_original = tx_alvo["valor"]
    tx_alvo["valor"] = valor_falso
    salvar(setor, dados)
    print(f"  🔴 {setor}: bloco #{bloco_alvo['index']} adulterado "
          f"(valor {valor_original} → {valor_falso})")
    return True


def aguardar(segundos, motivo=""):
    print()
    print(f"  ⏳ Aguardando {segundos}s{(' — ' + motivo) if motivo else ''}...")
    time.sleep(segundos)


# ─── ENVIO DE REQUISIÇÃO (reusado nos cenários) ────────────────────────────

def montar_payload(origem, ocorrencia, prioridade):
    dados = f"{origem}:{ocorrencia}:{prioridade}"
    assinatura = auth.assinar(origem, dados)
    return json.dumps({
        "ocorrencia": ocorrencia,
        "prioridade": prioridade,
        "origem": origem,
        "assinatura": assinatura
    })


def enviar_requisicao(setor_destino, prioridade=3):
    host, port = BROKERS_SENSORES[setor_destino]
    ocorrencia = OCORRENCIA_POR_PRIORIDADE[prioridade]
    payload = montar_payload(setor_destino, ocorrencia, prioridade)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        sock.sendall(payload.encode())
        sock.close()
        return True
    except Exception as e:
        print(f"  ⚠ falha ao enviar para {setor_destino}: {e}")
        return False


# ─── OPÇÃO 1 — N setores maliciosos, configurável ──────────────────────────

def opcao_setores_maliciosos():
    cabecalho("SIMULAR N SETORES MALICIOSOS")
    print("  Você escolhe quais setores adulterar e com qual valor falso cada um.")
    print("  Dica: use valores DIFERENTES entre si para simular ataques não")
    print("  coordenados (cada invasor adultera de um jeito diferente).")
    print()

    setores = perguntar_setores_multiplos("Quais setores adulterar?")
    if not setores:
        print("  nenhum setor válido selecionado, cancelando")
        return

    fazer_backup(setores)
    contador = 0
    for setor in setores:
        valor = perguntar_inteiro(f"  Valor falso para {setor}", default=90000 + contador * 11111)
        adulterar(setor, valor)
        contador += 1

    espera = perguntar_inteiro("Segundos para aguardar detecção + consenso", default=15, minimo=5, maximo=60)
    aguardar(espera, "ciclo de verificação de integridade (10s) + janela de consenso (4s)")

    print()
    print(f"  ✅ Confira os terminais de: {', '.join(setores)}")
    if len(setores) == 1:
        print(f"     Esperado: detecta corrupção, pede ajuda aos 2 peers honestos,")
        print(f"     ambos respondem igual → maioria 2/2 → restaura.")
    elif len(setores) == 2:
        print(f"     Esperado: cada um detecta a própria corrupção. Se os valores")
        print(f"     falsos usados forem DIFERENTES entre si, cada um só recebe")
        print(f"     1 resposta válida (a do setor honesto) e usa essa.")
    elif len(setores) == 3:
        print(f"     Esperado: nenhuma chain bate com outra → consenso impossível")
        print(f"     → '⚠ CONSENSO IMPOSSÍVEL' nos 3 — recuperação manual necessária.")
    print()
    print(f"  Para desfazer: use a opção de restaurar backups no menu.")


def opcao_restaurar():
    cabecalho("RESTAURAR BACKUPS")
    restaurar_backups()


# ─── OPÇÃO 2 — derrubar setor, modificar arquivo, subir e ver o que dá ────

def opcao_derrubar_modificar_subir():
    cabecalho("DERRUBAR UM SETOR, MODIFICAR O ARQUIVO E SUBIR DE NOVO")
    setor = perguntar_setor("Qual setor você vai derrubar e adulterar?")

    print()
    print(f"  📋 Roteiro deste cenário (parte manual, fora deste script):")
    print(f"     1. Vá até o terminal do broker '{setor}' e derrube com Ctrl+C")
    print(f"     2. Volte aqui e pressione enter — o script vai adulterar")
    print(f"        o arquivo {setor}_blockchain.json ENQUANTO ele está OFFLINE")
    print(f"        (simulando uma invasão que só é possível com o processo parado,")
    print(f"        já que com ele rodando haveria o lock de escrita do próprio broker)")
    print(f"     3. Depois, suba o broker de novo: python broker.py {setor}")
    print(f"     4. Observe o log de inicialização dele")
    print()
    input(f"  Já derrubou o broker '{setor}'? Pressione enter para adulterar o arquivo...")

    fazer_backup([setor])
    valor_falso = perguntar_inteiro("Valor falso a inserir", default=99999)
    sucesso = adulterar(setor, valor_falso)

    if not sucesso:
        print("  não foi possível adulterar (sem transações com 'valor' na chain)")
        return

    print()
    print(f"  ✅ Arquivo adulterado. Agora suba o broker de novo:")
    print(f"     python broker.py {setor}")
    print()
    print(f"  O que observar no log de inicialização:")
    print(f"     - 'carregar_do_disco()' deve rodar 'chain_valid()' sobre o arquivo")
    print(f"     - se detectar inválido: 'arquivo encontrado mas chain inválida — ignorado'")
    print(f"       e o broker sobe com uma blockchain NOVA (perde o histórico anterior)")
    print(f"     - OU, se você implementou recuperação na subida: ele deve buscar")
    print(f"       a chain válida dos peers automaticamente")
    print(f"     - compare se isso é o comportamento que vocês querem para a arguição:")
    print(f"       'o que acontece se o nó comprometido reiniciar?' é uma pergunta")
    print(f"       bem provável do professor.")


# ─── OPÇÃO 3 — derrubar setor, requisitar em outro, subir e conferir ──────

def opcao_derrubar_requisitar_subir():
    cabecalho("DERRUBAR UM SETOR, FAZER REQUISIÇÃO EM OUTRO E SUBIR DE NOVO")
    setor_derrubado = perguntar_setor("Qual setor você vai derrubar?")
    outros = [s for s in ARQUIVOS if s != setor_derrubado]
    setor_ativo = perguntar_setor(
        f"Em qual outro setor disparar a requisição? [{', '.join(outros)}]",
        default=outros[0]
    )
    if setor_ativo == setor_derrubado:
        setor_ativo = outros[0]
        print(f"  (corrigido para {setor_ativo}, precisa ser diferente do derrubado)")

    prioridade = perguntar_prioridade()

    print()
    print(f"  📋 Roteiro deste cenário:")
    print(f"     1. Vá até o terminal do broker '{setor_derrubado}' e derrube com Ctrl+C")
    print(f"     2. Volte aqui e pressione enter — o script vai disparar uma")
    print(f"        requisição real para '{setor_ativo}' enquanto '{setor_derrubado}' está offline")
    print(f"     3. Depois, suba '{setor_derrubado}' de novo: python broker.py {setor_derrubado}")
    print(f"     4. Confira se ele recebe (via BLOCK_NEW ou sync) o bloco que foi")
    print(f"        minerado enquanto estava fora, e se o saldo bate com os outros 2")
    print()
    input(f"  Já derrubou o broker '{setor_derrubado}'? Pressione enter para disparar a requisição...")

    enviado = enviar_requisicao(setor_ativo, prioridade)
    if enviado:
        print(f"  ✅ requisição enviada para {setor_ativo} com {setor_derrubado} offline")
    else:
        print(f"  ❌ falha ao enviar — '{setor_ativo}' está rodando?")
        return

    print()
    print(f"  Agora suba o broker de novo:")
    print(f"     python broker.py {setor_derrubado}")
    print()
    print(f"  O que observar:")
    print(f"     - '{setor_derrubado}' sobe com a chain ANTIGA (sem o bloco novo)")
    print(f"     - ele deve sincronizar com os outros e ATUALIZAR para a chain mais")
    print(f"       longa (via 'sync inicial' + eventual BLOCK_NEW/CHAIN_REQUEST)")
    print(f"     - compare o saldo de '{setor_ativo}' nos 3 brokers depois da sync —")
    print(f"       devem ficar idênticos, mesmo '{setor_derrubado}' tendo perdido o evento")
    print(f"       ao vivo")


# ─── MENU ───────────────────────────────────────────────────────────────────

OPCOES = {
    "1": ("Simular N setores maliciosos (você escolhe quais e os valores)", opcao_setores_maliciosos),
    "2": ("Derrubar um setor, adulterar o arquivo dele e subir de novo", opcao_derrubar_modificar_subir),
    "3": ("Derrubar um setor, requisitar em outro e subir de novo (testa sync)", opcao_derrubar_requisitar_subir),
    "4": ("Restaurar todos os backups (.backup) feitos pelas opções acima", opcao_restaurar),
}


def menu():
    while True:
        cabecalho("TESTE DE SETOR MALICIOSO E RESILIÊNCIA")
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
