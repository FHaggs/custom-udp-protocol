# RTP over UDP

Implementacao em Python do Reliable Transport Protocol descrito em 04 - Protocolo HTTP.pdf.

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
uv run rtp --port 9000 --mode saw --window 4 --input arquivo.bin
```

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
- O sender usa um par de portas locais efemero para evitar colisao com o receiver quando ambos rodam na mesma maquina.
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
