#!/usr/bin/env python3
"""worker.py — 模拟 GPU 测试机（本机独立子进程，无真机 / 无 GPU / 无网络）。

契约（见 GRAPH.md §0/§3/§4）：
  1. 一次"跑分" = sleep(node_work_seconds) 秒（+ slow_nodes 注入的额外延迟）。
  2. 退出码即节点成败：0 = 绿；非 0 = 挂（模拟 GPU 测试机故障 = 3）。
  3. 成功才写产物 shards/NN.json；失败/被杀不写产物。
  4. 全部日志落盘：PID、round、读到的每个 config 键值、退出原因。
  5. 阈值一律来自 --config 指向的 yaml，缺键直接报错退出（退出码 20），不给默认值。
  6. 注入开关语义：fail_nodes 命中 = 跑完即 exit 3；slow_nodes 命中 = 在 node_work_seconds 之上多 sleep；
     hang_nodes 命中 = 收到 SIGTERM 只记录、不退出（模拟死锁/挂死的机器），必须等 orchestrator 走完
     kill_grace_seconds 宽限后 SIGKILL —— 该路径的现场证据就是"日志停在 event=SIGNAL_RECEIVED、
     没有 WORK_END、没有 shard、进程以 -9 收场"。

本进程由 orchestrator 用 subprocess.Popen 独立发起；不感知其它节点，不做任何线程。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------- 常量（非阈值）
EXIT_OK = 0
EXIT_FAULT = 3          # 模拟 GPU 测试机故障（掉卡/驱动抖动）
EXIT_CONFIG = 20        # 配置不可用
EXIT_SIGTERM = 143      # 被 orchestrator terminate（超时分支的宽限阶段）

# 必须存在于 config.yaml 的键；缺任何一个 = 配置错误（GRAPH.md §5 的阈值清单）
REQUIRED_KEYS = (
    "nodes",
    "max_rounds",
    "per_node_timeout",
    "total_timeout",
    "node_work_seconds",
    "fail_nodes",
    "slow_nodes",
    "hang_nodes",
    "max_retries",
    "kill_grace_seconds",
    "poll_interval_seconds",
)


def load_config(path: Path) -> dict:
    """读 config.yaml；缺键即抛错，绝不静默补默认值。"""
    import yaml  # 延迟导入：让 --help 不依赖 yaml

    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"config {path} 不是 mapping")
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise KeyError(f"config 缺少键: {', '.join(missing)}")
    return raw


class RunLog:
    """key=value 一行一条、逐行 flush 的日志（被 SIGKILL 也不丢已有行）。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")
        self.path = path

    def write(self, event: str, **fields) -> None:
        parts = [f"{time.time():.3f}", f"pid={os.getpid()}", f"role=worker", f"event={event}"]
        for key, value in fields.items():
            if isinstance(value, (dict, list, tuple)):
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                text = str(value)
            if any(c.isspace() for c in text):  # 带空格的值加引号，保证 key=value 可被机器切分
                text = '"' + text + '"'
            parts.append(f"{key}={text}")
        self._fh.write(" ".join(parts) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="模拟 GPU 测试机 worker（单节点单次跑分）")
    ap.add_argument("--node", required=True, help="节点名，必须出现在 config.nodes 里")
    ap.add_argument("--config", required=True, help="config.yaml 路径（阈值唯一来源）")
    ap.add_argument("--round", required=True, type=int, help="本轮是编排的第几轮（1 基）")
    ap.add_argument("--out", required=True, help="本次 run 的产物根目录（shards/ logs/ 在它下面）")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out = Path(args.out).resolve()
    round_no = args.round

    # --- 先确定日志路径（节点序号 = config.nodes 中的 1 基序号）---
    try:
        cfg = load_config(Path(args.config).resolve())
    except Exception as exc:  # 配置错误是"节点起不来"，如实失败
        emergency = RunLog(out / "logs" / f"worker-{args.node}.round{round_no}.log")
        emergency.write("CONFIG_LOAD_FAILED", node=args.node, round=round_no, reason=repr(exc))
        emergency.close()
        print(f"worker config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    nodes = list(cfg["nodes"])
    if args.node not in nodes:
        bad = RunLog(out / "logs" / f"worker-{args.node}.round{round_no}.log")
        bad.write("CONFIG_INVALID", node=args.node, reason="node not in config.nodes",
                  config_nodes=nodes)
        bad.close()
        print(f"worker: unknown node {args.node}", file=sys.stderr)
        return EXIT_CONFIG

    index = nodes.index(args.node) + 1
    shard_name = f"{index:02d}"
    log = RunLog(out / "logs" / f"worker-{shard_name}.round{round_no}.log")

    fail_nodes = [str(n) for n in cfg["fail_nodes"]]
    slow_nodes = {str(k): float(v) for k, v in dict(cfg["slow_nodes"]).items()}
    hang_nodes = [str(n) for n in cfg["hang_nodes"]]
    work_seconds = float(cfg["node_work_seconds"])
    extra = float(slow_nodes.get(args.node, 0.0))
    sleep_seconds = work_seconds + extra
    hung = args.node in hang_nodes

    # --- 日志：读到的 config 值逐个回显（checker 不读代码即可核对阈值未被硬编码）---
    log.write("WORKER_START", node=args.node, node_index=index, round=round_no,
              config=str(Path(args.config).resolve()), ppid=os.getppid(),
              cwd=os.getcwd(), python=sys.version.split()[0])
    for key in REQUIRED_KEYS:
        log.write("CONFIG_READ", node=args.node, round=round_no, key=key, value=cfg[key])
    log.write("INJECTION_EVAL", node=args.node, round=round_no,
              fail_nodes=fail_nodes, fail_hit=args.node in fail_nodes,
              slow_nodes=slow_nodes, slow_extra_seconds=extra,
              hang_nodes=hang_nodes, hang_hit=hung,
              signal_policy="exit_on_sigterm" if not hung else "ignore_sigterm(hang injection)",
              node_work_seconds=work_seconds, sleep_seconds=sleep_seconds,
              per_node_timeout=cfg["per_node_timeout"],
              expected_artifact=f"shards/{shard_name}.json")

    # --- 被 terminate 时如实记录（超时分支的证据链）---
    def _on_signal(signum: int, _frame) -> None:
        sig = signal.Signals(signum).name
        log.write("SIGNAL_RECEIVED", node=args.node, round=round_no, signal=sig,
                  slept_so_far_s=round(time.time() - started_at, 3),
                  exit_reason=("ignored: node is in config.hang_nodes, waiting to be SIGKILLed"
                               if hung else "killed by orchestrator via %s" % sig),
                  action="ignored" if hung else "exiting",
                  planned_sleep_seconds=sleep_seconds)
        if hung:
            # 模拟死锁/挂死的机器：SIGTERM 叫不动它（不退出、不写 WORK_END、不写 shard）。
            # orchestrator 的 PROC_KILL 证据就是从这里开始的。
            print(f"node {args.node} ignoring {sig}: listed in config.hang_nodes "
                  f"(deadlock simulation)", file=sys.stderr, flush=True)
            return
        sys.exit(EXIT_SIGTERM)

    started_at = time.time()
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    log.write("WORK_BEGIN", node=args.node, round=round_no, sleep_seconds=sleep_seconds,
              started_at_epoch=round(started_at, 3))

    time.sleep(sleep_seconds)

    finished_at = time.time()
    duration = round(finished_at - started_at, 3)

    # --- 注入：fail_nodes 命中 = 跑分结束但结果失败，不写产物 ---
    if args.node in fail_nodes:
        log.write("WORK_END", node=args.node, round=round_no, status="failed",
                  exit_reason="simulated GPU fault (node listed in config.fail_nodes)",
                  duration_s=duration, artifact="none", exit_code=EXIT_FAULT)
        log.close()
        print(f"node {args.node} simulated GPU fault", file=sys.stderr)
        return EXIT_FAULT

    # --- 成功：写产物 shards/NN.json ---
    shards_dir = out / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    shard_path = shards_dir / f"{shard_name}.json"
    payload = {
        "node": args.node,
        "node_index": index,
        "shard": f"shards/{shard_name}.json",
        "pid": os.getpid(),
        "round": round_no,
        "status": "ok",
        "config_file": str(Path(args.config).resolve()),
        "config_read": {key: cfg[key] for key in REQUIRED_KEYS},
        "sleep_seconds_used": sleep_seconds,
        "started_at_epoch": round(started_at, 3),
        "finished_at_epoch": round(finished_at, 3),
        "duration_s": duration,
    }
    tmp = shard_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(shard_path)

    log.write("SHARD_WRITTEN", node=args.node, round=round_no, path=str(shard_path),
              bytes=shard_path.stat().st_size)
    log.write("WORK_END", node=args.node, round=round_no, status="ok",
              exit_reason="work completed, shard written", duration_s=duration,
              artifact=f"shards/{shard_name}.json", exit_code=EXIT_OK)
    log.close()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
