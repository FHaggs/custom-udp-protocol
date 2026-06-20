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
uv run rtp --listen --bind-host 0.0.0.0 --port 9000 --mode saw --window 4 --output recebido.bin
```

Sender:

```bash
uv run rtp --host 192.168.1.20 --bind-host 0.0.0.0 --port 9000 --mode saw --window 4 --input arquivo.bin
```

Argumentos principais:

- `--listen`: executa como receiver.
- `--host`: host do receiver em modo sender.
- `--bind-host`: interface local usada no bind. Esse argumento ajuda em testes locais.
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
- Segmentacao em pacotes de 255 bytes com pacote final de tamanho menor ou `0` quando o arquivo e multiplo exato de 255 bytes.
- Variantes stop-and-wait, Go-Back-N e Selective Repeat em um unico binario.

## Testes

```bash
uv run pytest
```