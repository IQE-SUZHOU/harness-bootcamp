# D3 Fixture

用于 maker-checker 演示的最小仓库。源数据在 `src/`，检查脚本在 `scripts/`。

## Benchmark

BENCH=1234

## 用法

```sh
bash scripts/check.sh
bash scripts/bench.sh
```

## 说明

- `scripts/check.sh` 比较 `src/answer.txt` 与 `src/expected.txt`
- `scripts/bench.sh` 由 `src/answer.txt` 推导基准值
