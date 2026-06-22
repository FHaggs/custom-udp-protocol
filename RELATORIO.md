# Relatorio Tecnico - RTP sobre UDP

## Identificacao

**Disciplina:** Laboratorio de Redes de Computadores  
**Trabalho:** Protocolo de transporte confiavel sobre UDP  
**Projeto:** Implementacao do Reliable Transport Protocol (RTP) com modos `saw`, `gbn` e `sr`

## 1. Objetivo

O objetivo deste trabalho foi projetar, implementar e avaliar um protocolo de transporte confiavel sobre UDP, chamado RTP, capaz de transferir arquivos entre dois hosts com mecanismos proprios de confiabilidade, ordenacao e controle de fluxo.

A implementacao foi dividida em tres variantes:

- `saw`: stop-and-wait;
- `gbn`: Go-Back-N;
- `sr`: Selective Repeat.

A avaliacao experimental foi feita com cenarios de latencia, perda e reordenacao, com coleta automatizada de metricas e validacao de integridade por hash SHA-256.

## 2. Visao Geral da Solucao

A solucao foi desenvolvida em Python, usando UDP como camada de transporte subjacente. Toda a logica de confiabilidade foi implementada na aplicacao, sem depender do sistema operacional para retransmissao, ordenacao ou controle de fluxo.

O protocolo implementado segue a especificacao fornecida no enunciado:

- cabecalho RTP de 9 bytes;
- numeros de sequencia de 14 bits;
- `CRC32` sobre cabecalho mais payload;
- handshake de tres vias com negociacao de janela;
- encerramento com `FIN` e `FIN+ACK`;
- timeout fixo de 100 ms;
- selecao de modo por linha de comando;
- modelo de portas com base em um unico parametro `P`, com o receiver escutando em `P` e o sender usando `P+1` para handshake, dados e controle.

Todos os cenarios executados nas baterias geraram `hash_match = yes`, o que indica que o arquivo recebido foi identico ao arquivo enviado em todos os casos medidos.

## 3. Organizacao do Codigo

A implementacao foi organizada para separar formato de protocolo, logica de transferencia e automacao de testes.

### 3.1 Estrutura principal

- `src/rtp/__main__.py`: ponto de entrada da CLI.
- `src/rtp/protocol.py`: definicao do cabecalho, serializacao, desserializacao, CRC32 e helpers do espaco de sequencia.
- `src/rtp/peer.py`: implementacao do sender e do receiver, incluindo handshake, transferencia e encerramento.
- `src/rtp/scenarios.py`: definicao dos cenarios e apoio ao runner automatizado.
- `tests/`: testes unitarios e de integracao.
- `scripts/netns_lab.sh`: cria o laboratorio com namespaces e `veth`.
- `scripts/run_required_batches.sh`: executa as baterias obrigatorias em sequencia.
- `results/`: armazena metricas, arquivos JSON, CSV, Markdown e capturas `.pcapng` por cenario.

### 3.2 Separacao de responsabilidades

A organizacao foi pensada para manter a logica modular:

- `protocol.py` define o formato do pacote no fio;
- `peer.py` define o comportamento do protocolo em execucao;
- `__main__.py` apenas traduz argumentos em execucao concreta;
- `scenarios.py` e os scripts automatizam os experimentos exigidos no trabalho.

Isso facilitou depuracao, testes e evolucao da implementacao entre a Parte 1 e a Parte 2.

## 4. Protocolo Implementado

### 4.1 Cabecalho RTP

O cabecalho possui 9 bytes, com os seguintes campos:

- `SEQ` com 14 bits;
- `SYN` com 1 bit;
- `FIN` com 1 bit;
- `ACK` com 14 bits;
- `ACK flag` com 1 bit;
- `NACK` com 1 bit;
- `Length` com 8 bits;
- `CRC32` com 32 bits.

A serializacao foi implementada por operacoes de deslocamento e mascara sobre um inteiro de 72 bits, sempre em big-endian.

### 4.2 Segmentacao

Os arquivos sao segmentados em pacotes com payload de ate 255 bytes. Quando o arquivo e multiplo exato de 255 bytes, a implementacao envia um pacote final com `Length = 0`, conforme a especificacao.

Nos experimentos automatizados foi utilizado um arquivo de 16320 bytes, correspondente a 64 blocos completos de 255 bytes. Por isso, cada transferencia inclui tambem um pacote final vazio para sinalizar fim de stream.

### 4.3 CRC32

O checksum `CRC32` e calculado sobre o cabecalho com o campo `crc32` zerado, concatenado ao payload. Na recepcao, o pacote so e aceito se o CRC recalculado coincidir com o valor recebido.

Pacotes corrompidos sao descartados silenciosamente, sem envio de `NACK`, em conformidade com a especificacao. Essa decisao evita construir mensagens de controle com base em um cabecalho potencialmente invalido.

### 4.4 Handshake e encerramento

O estabelecimento de conexao segue o modelo de tres vias:

1. o sender envia `SYN` com a janela proposta em `Length`;
2. o receiver responde com `SYN+ACK` contendo sua propria janela proposta;
3. o sender envia o `ACK` final.

A janela efetiva da sessao e o menor valor entre as duas janelas propostas.

O encerramento ocorre por `FIN` enviado pelo transmissor dos dados, seguido por `FIN+ACK` do receiver.

### 4.5 Modelo de portas

A implementacao foi ajustada para seguir o modelo `P` e `P+1` descrito no enunciado:

- o receiver escuta na porta base `P`;
- o sender usa `P+1` como porta local da sessao;
- os pacotes de controle retornam para essa porta do sender.

Esse ajuste foi importante principalmente para interoperabilidade com outras implementacoes.

## 5. Metodologia Experimental

Os cenarios foram executados com automacao em Linux usando:

- `ip netns` para simular dois hosts;
- um par `veth` para conectividade entre namespaces;
- `tc netem` para inserir latencia, perda e reordenacao;
- `tcpdump` para capturas `.pcapng`;
- um runner em Python para consolidar metricas e hashes.

As metricas coletadas por cenario foram:

- bytes transferidos;
- datagramas enviados;
- datagramas recebidos;
- retransmissoes;
- duracao;
- throughput do sender;
- hash de entrada e hash de saida.

Os cenarios obrigatorios executados foram:

- `saw`: `L0-L3` e `P0-P4`;
- `gbn`: `L0-L3`, `P0-P4` e `R0-R2`, com janelas `4` e `16`;
- `sr`: `L0-L3`, `P0-P4` e `R0-R2`, com janelas `4` e `16`.

## 6. Resultados Consolidados

### 6.1 Stop-and-Wait

| Cenario | Tipo | Valor | Hash | Throughput Sender (B/s) | Retransmissoes | Duracao Sender (s) |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| L0 | latencia | 0 | yes | 2096312.46 | 0 | 0.007785 |
| L1 | latencia | 50 | yes | 4797.00 | 0 | 3.402127 |
| L2 | latencia | 100 | yes | 2419.86 | 66 | 6.744181 |
| L3 | latencia | 150 | yes | 1614.90 | 67 | 10.105885 |
| P0 | perda | 0 | yes | 2117720.06 | 0 | 0.007706 |
| P1 | perda | 1 | yes | 134063.55 | 1 | 0.121733 |
| P2 | perda | 5 | yes | 38204.29 | 4 | 0.427177 |
| P3 | perda | 10 | yes | 17604.21 | 9 | 0.927051 |
| P4 | perda | 25 | yes | 7277.03 | 22 | 2.242673 |

### 6.2 Go-Back-N

| Janela | Cenario | Tipo | Valor | Hash | Throughput Sender (B/s) | Retransmissoes | Duracao Sender (s) |
| ---: | --- | --- | ---: | --- | ---: | ---: | ---: |
| 4 | L0 | latencia | 0 | yes | 3083240.12 | 0 | 0.005293 |
| 4 | L1 | latencia | 50 | yes | 16859.79 | 0 | 0.967984 |
| 4 | L2 | latencia | 100 | yes | 8514.24 | 47 | 1.916788 |
| 4 | L3 | latencia | 150 | yes | 5695.71 | 59 | 2.865312 |
| 4 | P0 | perda | 0 | yes | 2080548.33 | 0 | 0.007844 |
| 4 | P1 | perda | 1 | yes | 3001024.98 | 0 | 0.005438 |
| 4 | P2 | perda | 5 | yes | 2233222.91 | 36 | 0.007308 |
| 4 | P3 | perda | 10 | yes | 2095064.58 | 38 | 0.007790 |
| 4 | P4 | perda | 25 | yes | 37360.71 | 140 | 0.436823 |
| 4 | R0 | reordenacao | 0 | yes | 41137.25 | 0 | 0.396721 |
| 4 | R1 | reordenacao | 10 | yes | 40950.04 | 4 | 0.398534 |
| 4 | R2 | reordenacao | 25 | yes | 43236.08 | 24 | 0.377463 |
| 16 | L0 | latencia | 0 | yes | 2074104.76 | 0 | 0.007868 |
| 16 | L1 | latencia | 50 | yes | 45760.70 | 0 | 0.356638 |
| 16 | L2 | latencia | 100 | yes | 23040.29 | 2 | 0.708324 |
| 16 | L3 | latencia | 150 | yes | 15456.82 | 51 | 1.055845 |
| 16 | P0 | perda | 0 | yes | 2875659.45 | 0 | 0.005675 |
| 16 | P1 | perda | 1 | yes | 482678.44 | 296 | 0.033811 |
| 16 | P2 | perda | 5 | yes | 306161.62 | 749 | 0.053305 |
| 16 | P3 | perda | 10 | yes | 44213.36 | 1029 | 0.369119 |
| 16 | P4 | perda | 25 | yes | 186190.18 | 1438 | 0.087652 |
| 16 | R0 | reordenacao | 0 | yes | 110394.16 | 0 | 0.147834 |
| 16 | R1 | reordenacao | 10 | yes | 110788.47 | 0 | 0.147308 |
| 16 | R2 | reordenacao | 25 | yes | 83596.45 | 2181 | 0.195224 |

### 6.3 Selective Repeat

| Janela | Cenario | Tipo | Valor | Hash | Throughput Sender (B/s) | Retransmissoes | Duracao Sender (s) |
| ---: | --- | --- | ---: | --- | ---: | ---: | ---: |
| 4 | L0 | latencia | 0 | yes | 3233486.24 | 0 | 0.005047 |
| 4 | L1 | latencia | 50 | yes | 16825.05 | 0 | 0.969983 |
| 4 | L2 | latencia | 100 | yes | 8507.10 | 59 | 1.918398 |
| 4 | L3 | latencia | 150 | yes | 5699.28 | 67 | 2.863519 |
| 4 | P0 | perda | 0 | yes | 3329533.88 | 0 | 0.004902 |
| 4 | P1 | perda | 1 | yes | 2556558.37 | 3 | 0.006384 |
| 4 | P2 | perda | 5 | yes | 2984562.57 | 6 | 0.005468 |
| 4 | P3 | perda | 10 | yes | 1801987.02 | 17 | 0.009057 |
| 4 | P4 | perda | 25 | yes | 147857.02 | 28 | 0.110377 |
| 4 | R0 | reordenacao | 0 | yes | 41138.70 | 0 | 0.396707 |
| 4 | R1 | reordenacao | 10 | yes | 41207.42 | 0 | 0.396045 |
| 4 | R2 | reordenacao | 25 | yes | 39000.90 | 6 | 0.418452 |
| 16 | L0 | latencia | 0 | yes | 2655176.09 | 0 | 0.006146 |
| 16 | L1 | latencia | 50 | yes | 45793.56 | 0 | 0.356382 |
| 16 | L2 | latencia | 100 | yes | 22829.03 | 64 | 0.714879 |
| 16 | L3 | latencia | 150 | yes | 15424.10 | 67 | 1.058085 |
| 16 | P0 | perda | 0 | yes | 2123223.18 | 0 | 0.007686 |
| 16 | P1 | perda | 1 | yes | 843526.29 | 30 | 0.019347 |
| 16 | P2 | perda | 5 | yes | 1214114.98 | 32 | 0.013442 |
| 16 | P3 | perda | 10 | yes | 1186795.59 | 48 | 0.013751 |
| 16 | P4 | perda | 25 | yes | 39121.44 | 59 | 0.417163 |
| 16 | R0 | reordenacao | 0 | yes | 110481.35 | 0 | 0.147717 |
| 16 | R1 | reordenacao | 10 | yes | 111521.23 | 0 | 0.146340 |
| 16 | R2 | reordenacao | 25 | yes | 110011.30 | 0 | 0.148348 |

## 7. Analise Parte 1 - Stop-and-Wait

### 7.1 Throughput teorico maximo

Para stop-and-wait, a eficiencia classica do ARQ pode ser escrita como:

$$
U = \frac{T_{tx}}{T_{tx} + RTT}
$$

onde $T_{tx}$ e o tempo de transmissao do pacote de dados. Em termos de throughput util, isso pode ser reescrito como:

$$
Throughput \approx \frac{L}{RTT + T_{tx}}
$$

onde $L$ e o payload util por pacote.

Neste trabalho, o payload nominal por pacote e 255 bytes. Como os cenarios foram executados em laboratorio local com RTT muito baixo em `L0/P0`, o throughput teorico tende ao limite imposto pela pilha local, pelo sistema operacional e pela implementacao. Por isso, em `L0/P0`, os valores medidos foram altos:

- `L0`: 2096312.46 B/s;
- `P0`: 2117720.06 B/s.

Esses valores nao representam a capacidade maxima de um enlace fisico real, mas sim o comportamento da implementacao num ambiente com atraso praticamente nulo.

Ja nos cenarios com latencia artificial, o comportamento esperado da formula aparece claramente. Se considerarmos apenas a latencia adicional por pacote:

- em `L1`, com 50 ms, o throughput ideal de ordem de grandeza seria cerca de $255 / 0.05 \approx 5100$ B/s;
- o valor medido foi 4797.00 B/s.

Ou seja, o resultado experimental ficou muito proximo do esperado para stop-and-wait.

### 7.2 Analise dos cenarios de latencia

Os resultados de latencia mostram o comportamento tipico de stop-and-wait:

- `L0`: throughput muito alto e sem retransmissoes;
- `L1`: throughput cai para 4797.00 B/s, mas ainda sem retransmissoes;
- `L2`: throughput cai para 2419.86 B/s e aparecem 66 retransmissoes;
- `L3`: throughput cai ainda mais para 1614.90 B/s, com 67 retransmissoes.

A transicao entre `L1` e `L2` e o ponto principal. Em `L1`, a latencia adicional ainda fica abaixo do timeout de 100 ms, entao o ACK chega antes da expiracao do temporizador. Em `L2`, o atraso fica muito proximo do timeout configurado. Com isso, pequenas variacoes de escalonamento e processamento passam a disparar timeouts espurios, gerando retransmissoes mesmo sem perda real.

A passagem de `L2` para `L3` agrava esse efeito: com 150 ms de atraso, o sender frequentemente expira o temporizador antes de receber o ACK, entao retransmite quase todos os pacotes.

Esse comportamento aparece claramente nas metricas:

- `L1`: 0 retransmissoes;
- `L2`: 66 retransmissoes;
- `L3`: 67 retransmissoes.

### 7.3 Analise dos cenarios de perda

Nos cenarios de perda, o throughput caiu de forma monotonicamente decrescente a medida que a taxa de perda aumentou:

- `P0`: 2117720.06 B/s;
- `P1`: 134063.55 B/s;
- `P2`: 38204.29 B/s;
- `P3`: 17604.21 B/s;
- `P4`: 7277.03 B/s.

As retransmissoes tambem cresceram conforme esperado:

- `P1`: 1 retransmissao;
- `P2`: 4 retransmissoes;
- `P3`: 9 retransmissoes;
- `P4`: 22 retransmissoes.

A intuicao teorica e que, em stop-and-wait, cada perda bloqueia o envio do pacote seguinte ate expirar o timeout e ocorrer uma nova tentativa. Por isso, o impacto da perda e muito mais severo do que em protocolos com pipeline. O custo nao e apenas reenviar um pacote, mas tambem desperdiçar um intervalo inteiro de espera.

### 7.4 Comportamento do CRC32

A implementacao segue a regra de descartar silenciosamente pacotes corrompidos, deixando a retransmissao por conta do timeout do sender.

Os resumos gerados pela bateria automatizada nao incluem um cenario dedicado de corrupcao de bits com captura especifica para essa analise. Portanto, para a versao final em PDF, essa secao deve ser complementada com uma captura Wireshark de um experimento de corrupcao controlada, mostrando:

- recepcao de um pacote com checksum invalido;
- ausencia de `NACK` para esse pacote;
- retransmissao posterior por timeout do sender.

Mesmo sem esse cenario no sumario consolidado, a logica esta implementada e validada por testes automatizados no codigo.

## 8. Analise Parte 2 - GBN e SR

### 8.1 Comparacao sob latencia

O ganho de janela deslizante aparece de forma muito clara quando comparamos `saw`, `gbn` e `sr`.

#### Janela 4

No cenario `L3`:

- `saw`: 1614.90 B/s;
- `gbn` janela 4: 5695.71 B/s;
- `sr` janela 4: 5699.28 B/s.

#### Janela 16

No mesmo `L3`:

- `gbn` janela 16: 15456.82 B/s;
- `sr` janela 16: 15424.10 B/s.

A explicacao e direta: em stop-and-wait, o sender so pode ter um pacote em voo, entao a latencia domina completamente o desempenho. Em GBN e SR, varios pacotes ficam simultaneamente em transito. Isso permite preencher o canal mesmo quando o ACK de um pacote ainda nao voltou.

Em `L1`, `L2` e `L3`, o aumento da janela de `4` para `16` multiplicou o throughput em GBN e SR, confirmando o efeito esperado de pipeline.

### 8.2 Comparacao sob perda

Nos cenarios de perda, a principal diferenca entre GBN e SR aparece no numero de retransmissoes.

#### Janela 4

Em `P4`:

- `gbn`: 140 retransmissoes, 37360.71 B/s;
- `sr`: 28 retransmissoes, 147857.02 B/s;

#### Janela 16

Em `P3`:

- `gbn`: 1029 retransmissoes, 44213.36 B/s;
- `sr`: 48 retransmissoes, 1186795.59 B/s.

Em `P4` com janela 16 houve uma anomalia interessante:

- `gbn`: 1438 retransmissoes, 186190.18 B/s;
- `sr`: 59 retransmissoes, 39121.44 B/s.

Nesse caso especifico, embora SR tenha retransmitido muito menos, a execucao individual de `gbn` terminou mais rapidamente. Como o cenario de perda e estocastico e os dados correspondem a uma unica amostra por configuracao, esse ponto deve ser interpretado com cautela. O padrao dominante do conjunto continua sendo que SR sofre muito menos com perda do que GBN, especialmente em janelas maiores.

Conceitualmente, isso ocorre porque:

- em GBN, uma perda pode forcar o reenvio de todo o trecho da janela a partir do pacote faltante;
- em SR, apenas o pacote realmente perdido precisa ser retransmitido.

### 8.3 Comparacao sob reordenacao

Este foi o cenario mais importante da Parte 2.

#### Janela 4

No cenario `R2`:

- `gbn`: 24 retransmissoes, 43236.08 B/s;
- `sr`: 6 retransmissoes, 39000.90 B/s.

#### Janela 16

No cenario `R2`:

- `gbn`: 2181 retransmissoes, 83596.45 B/s;
- `sr`: 0 retransmissoes, 110011.30 B/s.

Esses numeros mostram exatamente a diferenca esperada pela teoria:

- em GBN, pacotes fora de ordem sao tratados como problema de sequenciamento e geram descarte mais retransmissao em lote;
- em SR, os pacotes fora de ordem sao bufferizados dentro da janela, e a entrega a aplicacao acontece quando a lacuna e preenchida.

Por isso a reordenacao afeta muito mais GBN do que SR, especialmente quando a janela cresce.

### 8.4 Impacto do tamanho de janela

O aumento de janela trouxe dois efeitos distintos.

#### Beneficio sob latencia

Em ambos os protocolos com janela deslizante, sair de janela `4` para `16` melhorou bastante o throughput em latencia:

- `gbn`, `L1`: 16859.79 B/s para 45760.70 B/s;
- `sr`, `L1`: 16825.05 B/s para 45793.56 B/s.

#### Custo sob perda para GBN

Ao mesmo tempo, o aumento da janela ampliou o custo de retransmissao no GBN:

- `gbn`, `P2`: 36 retransmissoes na janela `4` contra 749 na janela `16`;
- `gbn`, `P3`: 38 retransmissoes na janela `4` contra 1029 na janela `16`.

Em SR esse crescimento foi muito mais controlado:

- `sr`, `P2`: 6 retransmissoes na janela `4` e 32 na janela `16`;
- `sr`, `P3`: 17 retransmissoes na janela `4` e 48 na janela `16`.

Ou seja, janela maior aumenta o throughput potencial, mas no GBN tambem aumenta fortemente o custo de uma perda, porque mais pacotes em voo podem precisar ser retransmitidos juntos.

## 9. Conclusao Comparativa

Os resultados mostram um comportamento coerente com a teoria dos protocolos ARQ.

### Stop-and-Wait

E a variante mais simples e mais facil de validar, mas tambem a mais sensivel a latencia e perda. Funciona bem em redes muito pequenas e com RTT baixo, mas escala mal quando a rede introduz atraso ou perda moderada.

### Go-Back-N

Melhora bastante o throughput em relacao a stop-and-wait quando ha latencia, porque permite pipeline. No entanto, e bastante penalizado por perda e por reordenacao, principalmente com janelas maiores, ja que uma unica falha pode provocar retransmissao de muitos pacotes.

### Selective Repeat

Foi a variante mais robusta no conjunto geral. Em especial:

- manteve bom desempenho sob latencia com janela maior;
- reduziu drasticamente retransmissoes sob perda;
- foi claramente superior sob reordenacao.

Assim, a sintese final e:

- `saw` e adequado quando simplicidade vale mais do que desempenho;
- `gbn` e adequado quando existe latencia, mas pouca perda e pouca reordenacao;
- `sr` e a melhor escolha para redes mais adversas, com perda e reordenacao relevantes.

## 10. Teste de Interoperabilidade

Pensando na interoperabilidade com outros grupos, dois pontos foram particularmente importantes na implementacao final:

- seguir o formato exato do cabecalho e das flags de controle;
- aderir ao modelo de portas `P` e `P+1` descrito na especificacao.

Esse segundo ponto foi ajustado durante o desenvolvimento, pois uma implementacao que use portas locais efemeras pode funcionar em testes locais, mas falhar quando combinada com uma implementacao externa mais estrita em relacao ao enderecamento.

## 11. Solucao de Problemas com IA

Durante o desenvolvimento tivemos um problema importante relacionado ao handshake e ao reenvio de pacotes de controle.

### 11.1 Sintoma observado

Em cenarios com perda, especialmente quando havia atraso ou descarte de mensagens de controle, a sessao podia entrar em um estado inconsistente:

- o receiver reenviava `SYN+ACK` porque nao tinha certeza de que o `ACK` final havia chegado;
- o sender ja havia avancado para a fase de dados;
- em algumas execucoes, isso causava repeticao indevida de mensagens de handshake e travamentos intermitentes no inicio da transferencia.

### 11.2 Como a IA ajudou

Foi utilizada IA como ferramenta de apoio para analisar a interacao entre handshake, timeout e retransmissao. A principal contribuicao foi ajudar a formular a causa raiz de forma objetiva:

- se o `ACK` final do handshake se perder, o receiver continua legitimamente reenviando `SYN+ACK`;
- portanto, o sender precisa reconhecer um `SYN+ACK` duplicado mesmo depois de ja ter entrado na fase de dados;
- ao receber esse `SYN+ACK` duplicado, o comportamento correto nao e tratar isso como um `ACK` de dados, e sim reenviar o `ACK` final do handshake.

Ou seja, o problema nao era apenas de timeout, mas de maquina de estados incompleta para o caso de perda do terceiro passo do handshake.

### 11.3 Correcao aplicada

A correcao foi feita em duas frentes:

1. o sender passou a detectar `SYN+ACK` duplicado durante a espera por pacotes de controle e reenviar o `ACK` final do handshake;
2. foram adicionados testes automatizados especificos para garantir que esse comportamento nao voltasse a falhar.

Esse ajuste eliminou um problema real de robustez, principalmente em cenarios com perda mais alta.

### 11.4 Aprendizado pratico

O uso da IA foi util nao para substituir a analise do protocolo, mas para acelerar a identificacao da causa raiz e sugerir um recorte de depuracao mais preciso. A validacao final continuou dependendo de leitura da especificacao, inspecao do codigo, testes automatizados e observacao do comportamento experimental.

## 12. Consideracoes Finais

O trabalho resultou em uma implementacao funcional e modular de um protocolo confiavel sobre UDP, com cobertura dos tres modos exigidos no enunciado.

A automacao dos cenarios com coleta de metricas e hashes ajudou a transformar os testes obrigatorios em um processo reproduzivel, e os resultados confirmaram o comportamento esperado para cada estrategia de retransmissao.

Como fechamento:

- a Parte 1 mostrou claramente as limitacoes de stop-and-wait sob latencia e perda;
- a Parte 2 mostrou o ganho de throughput com janela deslizante;
- a comparacao entre GBN e SR evidenciou que bufferizacao seletiva traz vantagens relevantes em cenarios com perda e, principalmente, reordenacao.

## 13. Artefatos Utilizados

Os dados deste relatorio foram consolidados a partir dos seguintes artefatos do projeto:

- `results/saw/summary.md`
- `results/saw/summary.csv`
- `results/gbn/summary.md`
- `results/sr/summary.md`
- `README.md`
- `architecture.md`
- `testing.md`

As capturas `.pcapng` por cenario permanecem disponiveis nos subdiretorios de `results/` para complementar a versao final em PDF com evidencias visuais do comportamento no fio.
