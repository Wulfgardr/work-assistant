# Privacy broker benchmark — macOS, 2026-08-24

Command:

```bash
work-assistant benchmark-privacy --iterations 200 --body-kib 16 --budget-ms 25
```

Scope: synthetic local broker round trips only. The measurement excludes provider, model and internet latency.

| Case | Median | p95 | Maximum |
| --- | ---: | ---: | ---: |
| `off` | 0.6394 ms | 0.9165 ms | 1.5333 ms |
| `all` | 2.3307 ms | 2.8182 ms | 3.9202 ms |
| selective `allow_raw` | 0.6282 ms | 0.8626 ms | 1.0237 ms |
| selective pseudonymization | 2.3574 ms | 2.6955 ms | 3.8865 ms |

Measured `all` versus `off` p95 overhead: **1.9017 ms** for a 16 KiB synthetic body on this machine.

The result is within the selected 25 ms local overhead budget. It is not a cross-platform guarantee and does not justify `allow_raw`; run the bundled benchmark on the target machine.
