# Sistema Distribuído de Monitoramento com Drones

Projeto da disciplina de Redes de Computadores II — implementação de um sistema distribuído de despacho de drones para atendimento de ocorrências, com exclusão mútua distribuída via algoritmo de Ricart-Agrawala e fila de prioridade compartilhada entre múltiplos brokers.

---

## Visão Geral

O sistema simula um cenário de segurança pública em que sensores detectam ocorrências em diferentes setores e drones são despachados para atendê-las. A solução é composta por três tipos de módulos independentes que se comunicam via TCP:

- **Broker** — coordena o despacho de drones, mantém a fila de requisições e se comunica com os demais brokers para garantir consistência
- **Drone** — conecta-se a um broker, aguarda missões e reporta conclusão
- **Sensor** — detecta ocorrências e as envia ao broker do seu setor

Cada setor (`setor_a`, `setor_b`, `setor_c`) tem seu próprio broker, drone e sensor, mas todos compartilham uma fila distribuída e consistente.

---

## Arquitetura

```
Sensor A ──► Broker A ◄──── TCP ────► Broker B ◄── Sensor B
                │                          │
             Drone A                    Drone B
                │                          │
                └──────────────────────────┘
                         Fila compartilhada
                     (sincronizada via broadcast)
```

### Portas utilizadas

| Módulo         | Porta setor_a | Porta setor_b | Porta setor_c |
|----------------|---------------|---------------|---------------|
| Broker ↔ Broker (Ricart-Agrawala) | 5001 | 5002 | 5003 |
| Drone → Broker | 6001 | 6002 | 6003 |
| Sensor → Broker | 7001 | 7002 | 7003 |

---

## Algoritmo de Ricart-Agrawala

A exclusão mútua distribuída é implementada pelo algoritmo de **Ricart-Agrawala**, garantindo que apenas um broker por vez modifique a fila compartilhada.

### Funcionamento

1. Quando um broker quer acessar a seção crítica (adicionar ou remover da fila), ele envia um `REQUEST` com seu timestamp de Lamport para todos os outros brokers
2. Cada broker responde com `REPLY` imediatamente, ou adia a resposta se estiver na seção crítica ou tiver maior prioridade
3. O broker que receber `REPLY` de todos os peers entra na seção crítica
4. Ao sair, envia os `REPLY`s adiados

### Relógio de Lamport

O timestamp é mantido por um relógio lógico de Lamport: incrementado a cada evento local e atualizado ao receber mensagens com `max(local, recebido) + 1`, garantindo ordenação causal dos eventos.

---

## Fila de Prioridade Compartilhada

A fila é replicada em todos os brokers e mantida consistente via broadcast. Os critérios de ordenação são:

1. **Prioridade** (maior primeiro): `3 = ataque_concreto`, `2 = possivel_ataque`, `1 = averiguacao`
2. **Timestamp de Lamport** (menor primeiro) — desempate por ordem de chegada
3. **req_id** — desempate final determinístico

Cada requisição possui um `req_id` único no formato `setor_id:timestamp:uuid`, o que permite merge idempotente durante sincronização.

---

## Tolerância a Falhas

### Broker cai e volta

Quando um broker reinicia, ele executa uma sincronização inicial tripla com intervalo de 3 segundos:

```
sync inicial 1/3 → pede fila para peers ativos
sync inicial 2/3 → pega requisições que chegaram durante o primeiro sync
sync inicial 3/3 → garante consistência final
```

O merge é feito por `req_id`, sem duplicatas.

### Drone cai durante missão

Quando um drone desconecta enquanto atende uma requisição, o broker detecta a queda via `recv()` retornando vazio, recupera a requisição salva em `ocorrencia_atual` e a devolve ao topo da fila respeitando a prioridade original. Um broadcast notifica os outros brokers para que atualizem suas filas locais.

---

## Como Rodar

### Pré-requisitos

- Python 3.10+
- Sem dependências externas (apenas biblioteca padrão)

### Rodando localmente (uma máquina)

Abra um terminal para cada módulo e execute na ordem: brokers primeiro, depois drones, depois sensores.

```bash
# Brokers
python broker.py setor_a
python broker.py setor_b
python broker.py setor_c

# Drones
python drone.py drone_a1
python drone.py drone_b1
python drone.py drone_c1

# Sensores
python sensor.py setor_a
python sensor.py setor_b
python sensor.py setor_c
```

### Rodando em múltiplas máquinas

Descubra o IP de cada máquina com `hostname -I` e passe via variável de ambiente. O formato é `IP:PORTA`.

**Exemplo com 3 PCs:**

```bash
# PC com setor_a (IP 192.168.1.10)
python broker.py setor_a   # sem variáveis, pois é o próprio
# mas os peers precisam saber seu IP:

# PC com setor_b (IP 192.168.1.11) — broker
BROKER_A=192.168.1.10:5001 BROKER_B=192.168.1.11:5002 BROKER_C=192.168.1.12:5003 \
python broker.py setor_b

# Drone no mesmo PC do setor_b
BROKER_A=192.168.1.10:6001 BROKER_B=192.168.1.11:6002 BROKER_C=192.168.1.12:6003 \
python drone.py drone_b1

# Sensor no mesmo PC do setor_b
BROKER_A=192.168.1.10:7001 BROKER_B=192.168.1.11:7002 BROKER_C=192.168.1.12:7003 \
python sensor.py setor_b
```

> Drones e sensores podem rodar em qualquer máquina — basta apontar as variáveis para os IPs corretos. A porta muda conforme o módulo: `5001-5003` para broker↔broker, `6001-6003` para drones, `7001-7003` para sensores.

### Rodando com Docker

```bash
# Build
docker build -t lucasarguerra/redes2-broker:latest ./broker
docker build -t lucasarguerra/redes2-drone:latest   ./drone
docker build -t lucasarguerra/redes2-sensor:latest  ./sensor

# Broker
docker run -d --network host \
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

---

## Estrutura de Arquivos

```
.
├── broker/
│   ├── broker.py           # Lógica principal do broker
│   ├── RicartAgrawala.py   # Algoritmo de exclusão mútua
│   └── Dockerfile
├── drone/
│   ├── drone.py
│   └── Dockerfile
└── sensor/
    ├── sensor.py
    └── Dockerfile
```

---

## Mensagens do Protocolo

| Tipo | Descrição |
|------|-----------|
| `REQUEST` | Broker solicita acesso à seção crítica |
| `REPLY` | Broker concede acesso ao solicitante |
| `DRONE_UPDATE` | Notifica mudança de estado de um drone |
| `FILA_REQUISICAO` | Broadcast de nova requisição na fila |
| `FILA_REMOVIDA` | Broadcast de requisição atendida |
| `FILA_SYNC_REQUEST` | Broker recém-iniciado pede a fila atual |
| `FILA_SYNC_RESPONSE` | Resposta com a fila completa |
| `BROKER_OFFLINE` | Notifica queda de um broker para limpeza de fila |
| `EXECUTE` | Broker pede a outro broker que despache um drone remoto |
| `CADASTRO` | Drone se registra no broker |
| `DISPATCH` | Broker envia missão ao drone |
| `CONCLUIDO` | Drone informa conclusão da missão |
