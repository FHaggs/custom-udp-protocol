# RTP over UDP

Implementacao em Python do Reliable Transport Protocol

## Requisitos

- Python 3.12+
- uv

## Instalar

```bash
uv sync --dev
```

## Uso

Receiver:

```bash
uv run rtp --listen --bind-host 127.0.0.1 --port 9000 --mode saw --window 4 --output recebido.bin
```

Sender:

```bash
uv run rtp --port 9000 --mode saw --window 4 --input arquivo.bin
```

Teste local na mesma maquina:

```bash
uv run rtp --listen --bind-host 127.0.0.1 --port 9000 --mode saw --window 4 --output recebido.bin
uv run rtp --port 9000 --mode saw --window 4 --input pyproject.toml
```

Teste em LAN entre duas maquinas:

No receiver, escute em todas as interfaces ou fixe a interface da rede local:

```bash
uv run rtp --listen --bind-host 0.0.0.0 --port 9000 --mode saw --window 4 --output recebido.bin
```

No sender, informe o IP do receiver na LAN:

```bash
uv run rtp --host 192.168.1.10 --port 9000 --mode saw --window 4 --input arquivo.bin
```

Ou para testes locais 

```bash
uv run rtp --host 127.0.0.1 --port 9000 --mode saw --window 4 --input pyproject.toml
```

Como descobrir o IP correto:

- O IP que importa para o sender e o IP da maquina receiver na mesma rede local.
- Nao use `127.0.0.1` em maquinas diferentes; esse endereco sempre aponta para a propria maquina.
- No Linux, liste os IPv4 da maquina com:

```bash
hostname -I
ip -4 addr show
```

- Procure o endereco da interface conectada a LAN, por exemplo `192.168.x.x` ou `10.x.x.x`.
- Se quiser escutar so em uma interface especifica, troque `--bind-host 0.0.0.0` pelo IP local do receiver, por exemplo `--bind-host 192.168.1.10`.
- Antes de testar, confirme que as duas maquinas se alcancam com `ping` e que a porta UDP escolhida nao esta bloqueada por firewall.

O `--host` no sender e o destino do receiver. Em teste local ele pode ser omitido, porque o padrao ja e `127.0.0.1`.

Argumentos principais:

- `--listen`: executa como receiver.
- `--host`: host do receiver em modo sender. Em teste local, o padrao `127.0.0.1` ja basta.
- `--bind-host`: interface local usada no bind. Para receiver local, prefira `127.0.0.1` em vez de `0.0.0.0`.
- `--port`: porta base `P` definida na especificacao.
- `--mode`: `saw`, `gbn` ou `sr`.
- `--window`: janela proposta no handshake, de 1 a 255.
- `--input`: arquivo a transmitir no sender.
- `--output`: arquivo de destino no receiver.

## Comportamento implementado

- Header RTP de 9 bytes com `SEQ`, `SYN`, `FIN`, `ACK`, `ACK flag`, `NACK`, `Length` e `CRC32`.
- Three-way handshake com negociacao de janela pelo campo `Length`.
- Two-way close com `FIN` e `FIN+ACK`.
- Timeout fixo de 100 ms.
- O receiver escuta na porta base `P`, e o sender usa a porta local `P+1` para handshake, dados e controle.
- Segmentacao em pacotes de 255 bytes com pacote final de tamanho menor ou `0` quando o arquivo e multiplo exato de 255 bytes.
- Variantes stop-and-wait, Go-Back-N e Selective Repeat em um unico binario.

## Testes

```bash
uv run pytest
```

## Cenarios do trabalho

Para executar os cenarios obrigatorios com metricas e arquivos de captura, use o runner:

```bash
uv run rtp-scenarios --help
```

O procedimento recomendado com `ip netns`, `tc netem` e `tcpdump` esta descrito em `testing.md`.

Para rodar todas as baterias obrigatorias em sequencia, use:

```bash
sudo -E env "PATH=$PATH" bash scripts/run_required_batches.sh
```
