# Benchmark del broker su macOS — 24 agosto 2026

Comando:

```bash
work-assistant benchmark-privacy --iterations 200 --body-kib 16 --budget-ms 25
```

Il test misura solo andate e ritorni locali con contenuti sintetici. Esclude provider, modello e rete.

| Caso | Mediana | p95 | Massimo |
| --- | ---: | ---: | ---: |
| `off` | 0,6394 ms | 0,9165 ms | 1,5333 ms |
| `all` | 2,3307 ms | 2,8182 ms | 3,9202 ms |
| `selective` con `allow_raw` | 0,6282 ms | 0,8626 ms | 1,0237 ms |
| `selective` con pseudonimizzazione | 2,3574 ms | 2,6955 ms | 3,8865 ms |

L'incremento p95 di `all` rispetto a `off` è **1,9017 ms** per un corpo sintetico da 16 KiB su questa macchina.

Il risultato rientra nel limite locale scelto di 25 ms. Non è una garanzia multipiattaforma e non giustifica l'uso di `allow_raw`. Ripeti il benchmark sulla macchina target.
