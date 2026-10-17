# Confronto senza perdita sul video

Byte del flusso applicativo; verifica byte per byte superata.

## 5 frame al secondo

| Metodo | Byte totali | Risparmio sul completo | Delta scelti | Encode ms/frame PC | Decode ms/frame PC |
|---|---:|---:|---:|---:|---:|
| raw | 2,694,815 | 0.00% | 0 | 0.006 | 0.006 |
| full_zlib | 2,508,837 | 6.90% | 0 | 0.438 | 0.082 |
| delta64_zlib | 2,508,837 | 6.90% | 0 | 1.065 | 0.082 |
| xor_zlib | 2,401,249 | 10.89% | 138 | 0.885 | 0.092 |
| full_shuffle_zlib | 2,430,375 | 9.81% | 0 | 0.334 | 0.106 |
| xor_shuffle_zlib | 2,291,562 | 14.96% | 137 | 0.583 | 0.100 |

## 1 frame al secondo

| Metodo | Byte totali | Risparmio sul completo | Delta scelti | Encode ms/frame PC | Decode ms/frame PC |
|---|---:|---:|---:|---:|---:|
| raw | 553,918 | 0.00% | 0 | 0.005 | 0.005 |
| full_zlib | 515,760 | 6.89% | 0 | 0.404 | 0.075 |
| delta64_zlib | 515,760 | 6.89% | 0 | 0.896 | 0.076 |
| xor_zlib | 504,339 | 8.95% | 23 | 0.741 | 0.082 |
| full_shuffle_zlib | 499,607 | 9.80% | 0 | 0.307 | 0.099 |
| xor_shuffle_zlib | 485,721 | 12.31% | 21 | 0.543 | 0.100 |

## Limiti

- One video and one split; descriptive measurements, not general performance evidence.
- Application stream bytes include session, packet headers, zlib wrappers, checksums, and refreshes.
- TCP/IP, Wi-Fi, MQTT/HTTP/WebSocket overhead, retries, and connection setup are not measured.
- Python CPU codec timings exclude tensor extraction, inference, input/output files, and network.
- Persistent reference size excludes codec workspace, temporary arrays, and interpreter memory.
- Decoder is checked against original bytes for every frame in every round; no quantization.
- XOR is a bitwise residual, not arithmetic subtraction of activation values.
