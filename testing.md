# Testing Scenarios

Este documento descreve como executar os cenarios obrigatorios do trabalho com metricas e capturas.

## Resposta curta: eu preciso de VM ou rede virtual?

Para desenvolvimento local, nao e obrigatorio criar VMs.
No Linux, a forma mais leve e reproduzivel de simular dois hosts e usar:

- `ip netns` para criar dois network namespaces;
- um par `veth` entre eles;
- `tc netem` para aplicar latencia, perda e reordenacao;
- `tcpdump` para gerar as capturas `.pcapng`.

Essa abordagem e excelente para iterar rapido, repetir cenarios e coletar metricas.

## Mas isso basta para o trabalho?

Para desenvolvimento, sim.
Para a entrega e apresentacao, o texto do trabalho pede que os testes obrigatorios sejam realizados entre maquinas distintas do grupo.

Entao a recomendacao pratica e:

1. usar namespaces locais para desenvolver, depurar e automatizar todos os cenarios;
2. repetir os cenarios finais mais importantes em duas maquinas reais ou em duas VMs separadas antes da entrega;
3. usar essas execucoes finais para as capturas Wireshark e para a evidencia do relatorio.

Se voce tiver dois computadores, essa e a opcao mais segura.
Se nao tiver, duas VMs Linux separadas em rede bridge sao a melhor aproximacao operacional.

## O que foi criado no projeto

Foram adicionados dois componentes para isso:

- `rtp-scenarios`: runner em Python que executa os cenarios e coleta metricas em JSON, CSV e Markdown;
- `scripts/netns_lab.sh`: script para subir uma topologia local com dois namespaces conectados por um par `veth`.

## Metricas coletadas

O runner grava, para sender e receiver:

- bytes transferidos;
- datagramas enviados;
- datagramas recebidos;
- retransmissoes;
- duracao em segundos;
- throughput em bytes por segundo.

Tambem grava:

- hash SHA-256 do arquivo de entrada;
- hash SHA-256 do arquivo recebido;
- indicador `hash_match` para validar integridade da transferencia.

## Cenarios cobertos

### Parte 1

Para `saw`, o conjunto `required` executa:

- latencia: `L0`, `L1`, `L2`, `L3`;
- perda: `P0`, `P1`, `P2`, `P3`, `P4`.

### Parte 2

Para `gbn` e `sr`, o conjunto `required` executa:

- latencia: `L0`, `L1`, `L2`, `L3`;
- perda: `P0`, `P1`, `P2`, `P3`, `P4`;
- reordenacao: `R0`, `R1`, `R2`.

O runner aceita multiplas janelas. Isso cobre a exigencia de testar pelo menos dois tamanhos de janela em `gbn` e `sr`.

## Topologia recomendada no Linux

Suba o laboratorio local:

```bash
sudo scripts/netns_lab.sh up
sudo scripts/netns_lab.sh ping
```

Topologia criada:

- namespace sender: `rtp-tx`, interface `veth-tx`, IP `10.20.0.1/24`;
- namespace receiver: `rtp-rx`, interface `veth-rx`, IP `10.20.0.2/24`.

Quando terminar:

```bash
sudo scripts/netns_lab.sh down
```

## Exemplo: Parte 1 completa para stop-and-wait

```bash
sudo -E env "PATH=$PATH" uv run rtp-scenarios \
  --mode saw \
  --window 1 \
  --scenario-set required \
  --results-dir results/saw \
  --receiver-host 10.20.0.2 \
  --sender-bind-host 0.0.0.0 \
  --receiver-bind-host 0.0.0.0 \
  --tx-namespace rtp-tx \
  --rx-namespace rtp-rx \
  --tx-interface veth-tx \
  --impair-side sender \
  --capture-pcap
```

## Exemplo: Parte 2 para GBN com duas janelas

```bash
sudo -E env "PATH=$PATH" uv run rtp-scenarios \
  --mode gbn \
  --window 4 16 \
  --scenario-set required \
  --results-dir results/gbn \
  --receiver-host 10.20.0.2 \
  --sender-bind-host 0.0.0.0 \
  --receiver-bind-host 0.0.0.0 \
  --tx-namespace rtp-tx \
  --rx-namespace rtp-rx \
  --tx-interface veth-tx \
  --impair-side sender \
  --capture-pcap
```

## Exemplo: Parte 2 para SR com duas janelas

```bash
sudo -E env "PATH=$PATH" uv run rtp-scenarios \
  --mode sr \
  --window 4 16 \
  --scenario-set required \
  --results-dir results/sr \
  --receiver-host 10.20.0.2 \
  --sender-bind-host 0.0.0.0 \
  --receiver-bind-host 0.0.0.0 \
  --tx-namespace rtp-tx \
  --rx-namespace rtp-rx \
  --tx-interface veth-tx \
  --impair-side sender \
  --capture-pcap
```

## Comandos para rodar as baterias em sequencia

### Opcao 1: script unico

Depois de subir os namespaces:

```bash
sudo scripts/netns_lab.sh up
```

rode todas as baterias obrigatorias em sequencia com:

```bash
sudo -E env "PATH=$PATH" bash scripts/run_required_batches.sh
```

Isso executa, nessa ordem:

- `saw` com janela `1`;
- `gbn` com janelas `4` e `16`;
- `sr` com janelas `4` e `16`.

Os resultados ficam em:

- `results/saw`;
- `results/gbn`;
- `results/sr`.

### Opcao 2: comandos manuais em sequencia

Se preferir rodar manualmente, use exatamente esta sequencia.

Parte 1, stop-and-wait:

```bash
sudo -E env "PATH=$PATH" uv run rtp-scenarios \
  --mode saw \
  --window 1 \
  --scenario-set required \
  --results-dir results/saw \
  --receiver-host 10.20.0.2 \
  --sender-bind-host 0.0.0.0 \
  --receiver-bind-host 0.0.0.0 \
  --tx-namespace rtp-tx \
  --rx-namespace rtp-rx \
  --tx-interface veth-tx \
  --impair-side sender \
  --capture-pcap
```

Parte 2, Go-Back-N:

```bash
sudo -E env "PATH=$PATH" uv run rtp-scenarios \
  --mode gbn \
  --window 4 16 \
  --scenario-set required \
  --results-dir results/gbn \
  --receiver-host 10.20.0.2 \
  --sender-bind-host 0.0.0.0 \
  --receiver-bind-host 0.0.0.0 \
  --tx-namespace rtp-tx \
  --rx-namespace rtp-rx \
  --tx-interface veth-tx \
  --impair-side sender \
  --capture-pcap
```

Parte 2, Selective Repeat:

```bash
sudo -E env "PATH=$PATH" uv run rtp-scenarios \
  --mode sr \
  --window 4 16 \
  --scenario-set required \
  --results-dir results/sr \
  --receiver-host 10.20.0.2 \
  --sender-bind-host 0.0.0.0 \
  --receiver-bind-host 0.0.0.0 \
  --tx-namespace rtp-tx \
  --rx-namespace rtp-rx \
  --tx-interface veth-tx \
  --impair-side sender \
  --capture-pcap
```

### Sem capturas `.pcapng`

Se voce quiser primeiro medir rapidamente sem gravar capturas, rode:

```bash
sudo -E env "PATH=$PATH" CAPTURE_FLAG='' bash scripts/run_required_batches.sh
```

### Aplicando os cenarios no receiver em vez do sender

Se quiser mover o `netem` para o receiver:

```bash
sudo -E env "PATH=$PATH" \
  IMPAIR_SIDE=receiver \
  bash scripts/run_required_batches.sh
```

Nesse caso o script usa `veth-rx` automaticamente.

## Como o impairment e aplicado

O runner aplica `tc netem` em apenas um lado por vez, exatamente como o enunciado permite.

Por padrao, os exemplos acima aplicam no sender.
Os perfis sao:

- latencia `L*`: `delay Xms`;
- perda `P*`: `loss X%`;
- reordenacao `R*`: `delay 20ms reorder X% 50%`.

Se quiser mover o impairment para o receiver, use:

```bash
--impair-side receiver --rx-interface veth-rx
```

## Saida gerada

Em cada diretorio de resultado, o runner grava:

- `sender.log`;
- `receiver.log`;
- `sender_stats.json`;
- `receiver_stats.json`;
- `summary.json`;
- opcionalmente `capture_window<janela>.pcapng`.

Na raiz do lote, ele tambem grava:

- `summary.csv`;
- `summary.md`.

## Como usar isso no relatorio

Para cada linha do `summary.csv`, voce ja tem os campos centrais pedidos no trabalho:

- throughput medido;
- numero de retransmissoes;
- confirmacao de integridade por hash.

O restante do relatorio sai da combinacao de:

- essas metricas;
- observacao do comportamento nos `.pcapng`;
- formulas teoricas de eficiencia para comparar com o medido.

## Recomendacao final

Melhor fluxo de trabalho:

1. desenvolver e automatizar tudo com `ip netns` localmente;
2. validar os cenarios obrigatorios com o runner e revisar `summary.csv`;
3. repetir pelo menos as baterias finais e a interoperabilidade em duas maquinas reais ou duas VMs separadas;
4. gerar as capturas finais para o relatorio e apresentacao.
