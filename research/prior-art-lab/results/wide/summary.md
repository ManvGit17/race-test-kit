# Prior-art lab results

Command: `uv run --no-project --python 3.13 python run_all.py --rounds 20 --clients 50 --seats 10 --label wide`

| probe | strategy | rounds | oversold (database) | red: invariant | red: refused, not overlapped | red: tool error | median server spread ms | median client spread ms |
|---|---|---|---|---|---|---|---|---|
| threadpool | naive | 20 | 19 | 19 | 0 | 0 | 67.7 | 53.9 |
| barrier | naive | 20 | 20 | 20 | 0 | 0 | 52.2 | 31.1 |
| pytest-race | naive | 20 | 17 | 17 | 0 | 0 | 247.5 | 126.7 |
| pytest-together | naive | 20 | 20 | 0 | 20 | 0 | 52.9 | 30.0 |
| pytest-run-parallel | naive | 20 | 20 | 0 | 0 | 0 | 65.0 | 23.7 |
| pytest-asyncio-concurrent | naive | 20 | 19 | 0 | 0 | 0 | 103.3 | 79.5 |
| pytest-asyncio-concurrent-parametrize | naive | 3 | 0 | 0 | 0 | 3 | - | - |
| hypothesis-stateful | naive | 5 | 0 | 0 | 0 | 0 | 364.6 | 0.0 |
| schemathesis | naive | 5 | 0 | 0 | 0 | 0 | 23575.0 | - |
| barrier-vs-row_lock | row_lock | 20 | 0 | 0 | 0 | 0 | 67.5 | 28.3 |

oversold: rounds where the database held more reservations than seats (the race really happened). red: rounds where the probe's own test failed, by reason.
Versions per probe are in each `results/<label>/<probe>.json`.
