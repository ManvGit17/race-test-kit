# Prior-art lab results

Command: `uv run --no-project --python 3.13 python run_all.py --rounds 40 --clients 2 --seats 1 --label pair`

| probe | strategy | rounds | oversold (database) | red: invariant | red: refused, not overlapped | red: tool error | median server spread ms | median client spread ms |
|---|---|---|---|---|---|---|---|---|
| threadpool | naive | 40 | 40 | 40 | 0 | 0 | 0.2 | 0.6 |
| barrier | naive | 40 | 40 | 40 | 0 | 0 | 0.2 | 0.4 |
| pytest-race | naive | 40 | 19 | 19 | 0 | 0 | 15.4 | 0.6 |
| pytest-together | naive | 40 | 40 | 40 | 0 | 0 | 0.1 | 0.4 |
| pytest-run-parallel | naive | 40 | 40 | 0 | 0 | 0 | 0.2 | 0.1 |
| pytest-asyncio-concurrent | naive | 40 | 40 | 0 | 0 | 0 | 0.2 | 1.1 |
| pytest-asyncio-concurrent-parametrize | naive | 3 | 0 | 0 | 0 | 3 | - | - |
| hypothesis-stateful | naive | 5 | 0 | 0 | 0 | 0 | - | 0.0 |
| schemathesis | naive | 5 | 0 | 0 | 0 | 0 | 42913.7 | - |
| barrier-vs-row_lock | row_lock | 40 | 0 | 0 | 0 | 0 | 0.3 | 0.3 |

oversold: rounds where the database held more reservations than seats (the race really happened). red: rounds where the probe's own test failed, by reason.
Versions per probe are in each `results/<label>/<probe>.json`.
