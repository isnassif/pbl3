# Sistema Distribuído de Monitoramento com Drones

Projeto da disciplina de Redes de Computadores II — implementação de um sistema distribuído de despacho de drones para atendimento de ocorrências, com exclusão mútua distribuída via algoritmo de Ricart-Agrawala, fila de prioridade compartilhada entre múltiplos brokers, tolerância a falhas de brokers e drones, e subsistema de integridade baseado em blockchain com autenticação HMAC e créditos tokenizados por setor.

---

## Visão Geral

O sistema simula um cenário de segurança pública em que sensores detectam ocorrências em diferentes setores e drones são despachados para atendê-las com base em prioridade. A solução é composta por módulos independentes que se comunicam via TCP:

- **Broker** — coordena o despacho de drones, mantém a fila de requisições compartilhada, se comunica com os demais brokers para garantir consistência distribuída e gerencia o subsistema de blockchain
- **Drone** — conecta-se a um broker, aguarda missões e reporta conclusão ou queda
- **Sensor** — detecta ocorrências aleatórias e as envia ao broker do seu setor
- **Cliente** — cliente manual interativo que permite enviar ocorrências de qualquer prioridade para um setor escolhido

Cada setor (`setor_a`, `setor_b`, `setor_c`) tem seu próprio broker, drone e sensor. Apesar de independentes, todos compartilham uma fila de requisições distribuída, replicada e consistente entre os três brokers.

---

## Arquitetura

```
Sensor A ──► Broker A ◄──── TCP (Ricart-Agrawala) ────► Broker B ◄── Sensor B
                │                                             │
             Drone A                                       Drone B
                │                                             │
                └──────────────── Fila Compartilhada ─────────┘
                              (replicada via broadcast)
                                         │
                                      Broker C ◄── Sensor C
                                         │
                                      Drone C

Cada Broker mantém internamente:
  ┌──────────────────────────────────────────┐
  │  GerenciadorAutenticacao  (assinatura)   │  ← verifica HMAC das mensagens
  │  GerenciadorTokens        (token)        │  ← controla saldo por setor
  │  BlockChain               (blockchain)   │  ← registra pagamentos em blocos
  └──────────────────────────────────────────┘
```

### Portas utilizadas

| Módulo | setor_a | setor_b | setor_c |
|--------|---------|---------|---------| 
| Broker ↔ Broker (Ricart-Agrawala) | 5001 | 5002 | 5003 |
| Drone → Broker | 6001 | 6002 | 6003 |
| Sensor → Broker | 7001 | 7002 | 7003 |

---

## Algoritmo de Ricart-Agrawala

A exclusão mútua distribuída é implementada pelo algoritmo de **Ricart-Agrawala**, garantindo que apenas um broker por vez modifique a fila compartilhada. Sem essa garantia, dois brokers poderiam despachar o mesmo drone simultaneamente para ocorrências diferentes, causando inconsistência.

### Funcionamento

1. Quando um broker quer acessar a seção crítica (adicionar ou remover da fila, despachar um drone), ele incrementa seu clock de Lamport e envia `REQUEST` com o timestamp para todos os peers
2. Cada peer responde com `REPLY` imediatamente se estiver `RELEASED`, ou adia a resposta se estiver `HELD` (na seção crítica) ou `WANTED` com timestamp menor (maior prioridade)
3. O broker que receber `REPLY` de todos os peers entra na seção crítica (`HELD`)
4. Ao sair, envia os `REPLY`s que foram adiados, liberando os peers que estavam esperando

### Relógio de Lamport

O timestamp lógico é mantido por um relógio de Lamport:
- Incrementado a cada evento local (`_incrementarClock`)
- Atualizado ao receber mensagens com `max(local, recebido) + 1` (`_atualizarClock`)

Isso garante ordenação causal dos eventos entre os três brokers, mesmo sem relógio físico sincronizado.

### O que o Ricart-Agrawala garante neste sistema

- **Exclusão mútua** — só um broker por vez opera sobre a fila
- **Ausência de deadlock** — o desempate por timestamp e ID do broker garante que sempre um dos brokers avança
- **Ausência de starvation** — todos os brokers eventualmente recebem permissão, pois as respostas adiadas são sempre enviadas na saída da seção crítica

---

## Fila de Prioridade Compartilhada

A fila é replicada em todos os brokers e mantida consistente via broadcast. Cada requisição possui um identificador único (`req_id`) no formato `setor_id:timestamp:uuid`, que permite:

- Merge idempotente durante sincronização (sem duplicatas)
- Remoção exata por ID ao atender uma requisição
- Desempate determinístico na ordenação

### Critérios de ordenação

| Critério | Direção | Descrição |
|----------|---------|-----------| 
| Prioridade | Decrescente | `3 = ataque_concreto` > `2 = possivel_ataque` > `1 = averiguacao` |
| Timestamp de Lamport | Crescente | Quem chegou primeiro dentro da mesma prioridade |
| req_id | Crescente | Desempate final determinístico |

### Fluxo de uma requisição

```
Sensor detecta ocorrência
        ↓
Broker recebe via TCP (porta 7xxx)
        ↓
Broker verifica assinatura HMAC do sensor
        ↓
Broker debita crédito do setor (GerenciadorTokens)
        ↓
Broker pede permissão ao Ricart-Agrawala
        ↓
[SEÇÃO CRÍTICA]
  Há drone livre e fila vazia?
  ├── SIM → despacha drone diretamente
  └── NÃO → insere na fila + broadcast para peers
[FIM DA SEÇÃO CRÍTICA]
        ↓
Drone conclui missão → broker grava laudo na blockchain + minera bloco
```

---

## Subsistema de Blockchain

O subsistema de integridade é composto por três módulos em `broker/blockchain/`, todos sem dependências externas (apenas biblioteca padrão do Python).

### `blockchain.py` — Cadeia de Blocos

Implementa uma blockchain simples com Proof of Work (PoW) e persistência atômica em disco.

**Estrutura de um bloco:**

```json
{
  "index": 2,
  "timestamp": "2026-06-17 23:18:00.123456",
  "proof": 533,
  "previous_hash": "0000a3f1...",
  "transacoes": [
    { "tipo": "PAGAMENTO", "valor": 10, "empresa": "setor_a", "ocorrencia": "...", "req_id": "..." }
  ]
}
```

**Funcionamento:**

- O bloco gênesis é minerado na primeira execução com as emissões iniciais de crédito (100 por setor) já incluídas como transações pendentes
- Cada laudo de ocorrência atendida gera um bloco novo, minerado com PoW de 4 zeros iniciais no hash SHA-256
- A chain é salva em disco de forma atômica (escrita em `.tmp` + `os.replace`) a cada novo bloco, evitando corrupção em caso de queda durante a escrita
- No reinício, o broker restaura a chain do disco se ela for válida e recalcula os saldos; caso contrário, inicia uma nova chain do zero

**Persistência por setor:**

Cada broker grava sua chain em um arquivo separado por setor, dentro de `broker/data/`:

| Setor | Arquivo |
|-------|---------|
| setor_a | `broker/data/setor_a_blockchain.json` |
| setor_b | `broker/data/setor_b_blockchain.json` |
| setor_c | `broker/data/setor_c_blockchain.json` |

Em Docker, `broker/data/` deve ser montado como volume para sobreviver a reinicializações do container.

### `token.py` — Créditos por Setor

Gerencia o saldo de créditos de cada setor e registra todas as movimentações como transações na blockchain.

**Operações disponíveis:**

| Método | Descrição | Tipo de transação gravada |
|--------|-----------|---------------------------|
| `emitir_creditos(empresa, valor)` | Adiciona créditos ao saldo do setor | `EMISSAO` |
| `gastar(empresa, valor, ocorrencia, req_id)` | Debita créditos ao atender uma ocorrência | `PAGAMENTO` |
| `transferir(origem, destino, valor)` | Move créditos entre setores | `TRANSFERENCIA` |
| `consultar_saldo(empresa)` | Retorna saldo atual em memória | — |
| `recuperar_creditos(empresa)` | Recalcula saldo percorrendo toda a chain | — |
| `recalcular_saldos()` | Reconstrói saldos de todos os setores a partir do disco | — |

**Inicialização:** cada setor começa com 100 créditos emitidos no bloco gênesis. Quando o broker reinicia e restaura a chain do disco, `recalcular_saldos()` recompõe os saldos em memória sem nova emissão, evitando duplicidade.

**Thread-safety:** todas as operações de escrita usam `threading.Lock`, garantindo consistência mesmo com múltiplas threads acessando o gerenciador simultaneamente.

### `assinatura.py` — Autenticação HMAC

Autentica mensagens entre sensores e brokers usando HMAC-SHA256 com chave compartilhada por setor, impedindo que um setor envie requisições se passando por outro.

**Chaves pré-compartilhadas (PSK):**

| Setor | Chave |
|-------|-------|
| setor_a | `chave_do_setor_a` |
| setor_b | `chave_do_setor_b` |
| setor_c | `chave_do_setor_c` |

**Fluxo de autenticação:**

```
Sensor monta a mensagem JSON
        ↓
Sensor chama assinar(setor, dados) → HMAC-SHA256(chave_setor, dados)
        ↓
Sensor envia { "ocorrencia": "...", ..., "assinatura": "<hex>" }
        ↓
Broker recebe e chama verificar(setor, dados, assinatura_recebida)
        ↓
  hmac.compare_digest(esperado, recebido)
  ├── True  → mensagem aceita, segue para fila
  └── False → mensagem descartada ("ASSINATURA INVÁLIDA" no log)
```

A comparação usa `hmac.compare_digest` (tempo constante) para evitar ataques de timing.

---

## Tolerância a Falhas

### Broker cai e volta

Quando um broker reinicia, ele não começa com fila vazia — executa uma **sincronização inicial tripla** com intervalo de 3 segundos para garantir que captura até as requisições que chegaram durante o próprio processo de sync:

```
sync 1/3 → pede fila para peers ativos
           (aguarda 3s — novas requisições podem ter chegado)
sync 2/3 → pede fila novamente para capturar o que chegou
           (aguarda 3s)
sync 3/3 → última rodada de nivelamento
```

O merge em cada sync é feito por `req_id` — requisições já presentes localmente não são duplicadas. Após os 9 segundos iniciais, o broker está nivelado com os peers e os broadcasts normais mantêm a consistência em tempo real.

**Blockchain na reconexão:** se o arquivo de chain persistido em `broker/data/` for válido, o broker o restaura e recalcula os saldos em memória; se estiver corrompido ou ausente, uma nova chain é iniciada do zero com nova emissão de gênesis.

**Importante:** as requisições **não são removidas da fila** quando um broker cai. Os brokers que ficaram ativos continuam com a fila íntegra e o broker que voltar a recebe completa via sync.

### Drone cai durante missão

Quando um drone desconecta enquanto está em missão ativa, o broker:

1. Detecta a queda via `recv()` retornando vazio no `_loopDrone`
2. Recupera a requisição salva em `ocorrencia_atual` (campo preenchido no momento do despacho)
3. Reinsere a requisição na fila respeitando a prioridade original
4. Faz broadcast `FILA_REQUISICAO` para que todos os outros brokers também reinsiram a requisição
5. Exibe o banner de recuperação no terminal

Se o drone desconectar sem missão ativa (apenas idle), nenhuma requisição é perdida e o sistema continua normalmente.

### Falha na comunicação entre brokers

Quando um broker tenta enviar mensagem a um peer e a conexão falha (timeout de 2 segundos), o envio é ignorado silenciosamente. O peer offline simplesmente não recebe o broadcast. Quando esse peer voltar, o sync inicial vai nivelar a fila.

---

## Protocolo de Mensagens

Toda comunicação entre módulos é feita via JSON sobre TCP.

| Tipo | Entre | Descrição |
|------|-------|-----------|
| `REQUEST` | Broker → Broker | Solicita acesso à seção crítica (Ricart-Agrawala) |
| `REPLY` | Broker → Broker | Concede acesso ao solicitante |
| `BROKER_OFFLINE` | Broker → Broker | Notifica queda de um peer; destinatários limpam as requisições daquele broker da fila |
| `DRONE_UPDATE` | Broker → Broker | Notifica mudança de estado de um drone (livre/ocupado) |
| `FILA_REQUISICAO` | Broker → Broker | Broadcast de nova requisição adicionada à fila |
| `FILA_REMOVIDA` | Broker → Broker | Broadcast de requisição atendida (remove por req_id) |
| `FILA_SYNC_REQUEST` | Broker → Broker | Broker recém-iniciado pede a fila atual |
| `FILA_SYNC_RESPONSE` | Broker → Broker | Resposta com a fila completa para merge |
| `EXECUTE` | Broker → Broker | Pede a outro broker que despache um drone remoto |
| `TRANSFERIR` | Broker → Broker | Solicita transferência de créditos entre setores |
| `CHAIN_REQUEST` | Broker → Broker | Solicita a chain completa de um peer (sincronização de blockchain) |
| `CHAIN_RESPONSE` | Broker → Broker | Resposta com a chain completa |
| `BLOCK_NEW` | Broker → Broker | Propaga novo bloco minerado para os peers |
| `CADASTRO` | Drone → Broker | Drone se registra ao conectar |
| `DISPATCH` | Broker → Drone | Envia missão ao drone |
| `CONCLUIDO` | Drone → Broker | Drone informa conclusão da missão |

> **Nota:** o sensor não usa um campo `"type"` — ele envia diretamente um payload JSON com os campos `ocorrencia`, `prioridade`, `origem` e `assinatura`.

---

## Como Rodar

### Pré-requisitos

- Python 3.10+
- Sem dependências externas (apenas biblioteca padrão)

### Localmente (uma máquina, sem Docker)

Abra um terminal por módulo e suba na ordem: brokers → drones → sensores.

```bash
# Brokers (rodar a partir do diretório broker/)
python broker.py setor_a
python broker.py setor_b
python broker.py setor_c

# Drones (rodar a partir do diretório drone/)
python drone.py drone_a1
python drone.py drone_b1
python drone.py drone_c1

# Sensores (rodar a partir do diretório sensor/)
python sensor.py setor_a
python sensor.py setor_b
python sensor.py setor_c

# Cliente manual (opcional, rodar a partir do diretório cliente/)
python cliente.py setor_a
```

Os defaults já apontam para `127.0.0.1` — nenhuma variável de ambiente é necessária para rodar localmente.

### Em múltiplas máquinas (laboratório)

Descubra o IP de cada máquina com `hostname -I` e passe via variável de ambiente no formato `IP:PORTA`.

```bash
# Máquina com setor_a (IP 192.168.1.10)
BROKER_A=192.168.1.10:5001 BROKER_B=192.168.1.11:5002 BROKER_C=192.168.1.12:5003 \
python broker.py setor_a

# Drone na mesma máquina
BROKER_A=192.168.1.10:6001 BROKER_B=192.168.1.11:6002 BROKER_C=192.168.1.12:6003 \
python drone.py drone_a1

# Sensor na mesma máquina
BROKER_A=192.168.1.10:7001 BROKER_B=192.168.1.11:7002 BROKER_C=192.168.1.12:7003 \
python sensor.py setor_a
```

> Drones e sensores podem rodar em qualquer máquina da rede — basta apontar as variáveis para os IPs corretos. A porta muda conforme o módulo: `5001–5003` para broker↔broker, `6001–6003` para drones, `7001–7003` para sensores.

### Com Docker

```bash
# Build das imagens
docker build -t lucasarguerra/redes2-broker:latest ./broker
docker build -t lucasarguerra/redes2-drone:latest  ./drone
docker build -t lucasarguerra/redes2-sensor:latest ./sensor

# Push para o Docker Hub
docker push lucasarguerra/redes2-broker:latest
docker push lucasarguerra/redes2-drone:latest
docker push lucasarguerra/redes2-sensor:latest

# Broker — monte broker/data como volume para persistir a blockchain entre reinicializações
docker run -d --network host \
  -v ./broker/data:/app/data \
  -e BROKER_A=<IP_A>:5001 -e BROKER_B=<IP_B>:5002 -e BROKER_C=<IP_C>:5003 \
  lucasarguerra/redes2-broker:latest python broker.py setor_a

# Drone
docker run -d --network host \
  -e BROKER_A=<IP_A>:6001 -e BROKER_B=<IP_B>:6002 -e BROKER_C=<IP_C>:6003 \
  lucasarguerra/redes2-drone:latest python drone.py drone_a1

# Sensor
docker run -d --network host \
  -e BROKER_A=<IP_A>:7001 -e BROKER_B=<IP_B>:7002 -e BROKER_C=<IP_C>:7003 \
  lucasarguerra/redes2-sensor:latest python sensor.py setor_a
```

Para ver os logs de um container rodando em background:

```bash
docker logs -f <ID_DO_CONTAINER>
docker ps  # lista containers ativos e seus IDs
```

---

## Testes

A pasta `testes/` contém scripts para validar o sistema sob diferentes condições. Os brokers precisam estar rodando antes de executar qualquer teste que envolva rede.

### `teste.py` — suite de testes unitários e de integração

Suite completa com `unittest` que cobre os principais critérios do sistema.

```bash
python testes/teste.py
```

| Classe de teste | O que verifica |
|-----------------|----------------|
| `CriterioArquitetura` | Conectividade e estrutura do cluster de brokers |
| `CriterioComunicacao` | Troca de mensagens entre brokers |
| `CriterioGestaoDeAtivos` | Emissão, gasto e saldo de créditos via blockchain |
| `CriterioPrevencaoDuploGasto` | Rejeição de operações com saldo insuficiente |
| `CriterioRequisicaoEPagamento` | Fluxo completo de ocorrência → despacho → pagamento |
| `CriterioLogImutavel` | Integridade e imutabilidade da chain |
| `CriterioTransparencia` | Consulta e auditabilidade das transações gravadas |

### `teste_assinatura.py` — autenticação HMAC

Valida o `GerenciadorAutenticacao` em dois modos:

```bash
# Modo isolado — sem rede, testa assinatura e verificação diretamente
python testes/teste_assinatura.py

# Modo rede — envia mensagens com assinatura forjada para brokers ativos
# e verifica que são rejeitadas no log ("ASSINATURA INVÁLIDA")
python testes/teste_assinatura.py --rede
```

| Caso testado | Resultado esperado |
|---|---|
| Setor autentica mensagem legítima | ✅ Verificação aceita |
| Setor A tenta se passar por setor B | ❌ Assinatura inválida |
| Mensagem adulterada após assinatura | ❌ Assinatura inválida |
| Ataque de rede com identidade forjada | Rejeitado no broker (confira o log) |

### `teste_duplogasto.py` — prevenção de duplo gasto (menu interativo)

Permite configurar setor alvo, prioridade e número de requisições para simular tentativas de gastar mais créditos do que o saldo disponível.

```bash
python testes/teste_duplogasto.py
```

### `teste_setormalicioso.py` — setor malicioso e resiliência (menu interativo)

Manipula diretamente os arquivos `{setor}_blockchain.json` em disco, simulando adulteração externa da chain, e guia cenários que exigem derrubar e subir brokers manualmente para verificar a detecção de corrupção.

```bash
python testes/teste_setormalicioso.py
```

---

## Estrutura de Arquivos

```
.
├── broker/
│   ├── broker.py               # Lógica principal: fila, despacho, tolerância a falhas
│   ├── RicartAgrawala.py       # Exclusão mútua distribuída + roteador de mensagens
│   ├── Dockerfile
│   ├── data/                   # Chain persistida por setor (gerada em execução)
│   │   ├── setor_a_blockchain.json
│   │   ├── setor_b_blockchain.json
│   │   └── setor_c_blockchain.json
│   └── blockchain/
│       ├── blockchain.py       # Cadeia de blocos: PoW, persistência, validação
│       ├── token.py            # Créditos por setor: emissão, pagamento, transferência
│       └── assinatura.py       # Autenticação HMAC-SHA256 por setor
├── cliente/
│   ├── cliente.py              # Cliente manual interativo para envio de ocorrências
│   └── Dockerfile
├── drone/
│   ├── drone.py                # Cliente TCP: recebe missões, reporta conclusão
│   └── Dockerfile
├── sensor/
│   ├── sensor.py               # Gerador de ocorrências aleatórias
│   └── Dockerfile
├── testes/
│   ├── teste.py                # Suite unittest: arquitetura, comunicação, blockchain
│   ├── teste_assinatura.py     # Testes de autenticação HMAC (isolado e via rede)
│   ├── teste_duplogasto.py     # Prevenção de duplo gasto (menu interativo)
│   └── teste_setormalicioso.py # Setor malicioso e resiliência a quedas (menu interativo)
└── docker-compose.yml          # Orquestração completa (brokers + drones + sensores)
```
