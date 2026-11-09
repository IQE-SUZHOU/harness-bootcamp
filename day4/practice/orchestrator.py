#!/usr/bin/env python3
"""orchestrator.py — 3 节点 GPU 测试编排（节点 = 本机独立子进程模拟 GPU 测试机）。

流程契约见 GRAPH.md：
  dispatch fan-out  : 同一 round 内对每个 pending 节点各一次 subprocess.Popen，中间不 wait（真并行）
  collect (fan-in)  : 轮询 poll() 收退出码；per_node_timeout 到点 terminate →(kill_grace_seconds)→ kill
  分支               : 全绿→交付 / 节点失败→重试≤max_retries / 重试耗尽→failed / 超时→人工分支
  失败传播           : worker 非 0 退出码 → 节点 failed → REPORT 行 + 主流程退出码非 0（不吞、不假成功）
  报错落盘           : 每次尝试的 worker stderr 重定向到 logs/worker-NN.roundR.err，REPORT/state 均引用它

所有阈值来自 config.yaml（缺键 = 退出码 20）。代码里不出现任何写死的阈值数字。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

EXIT_DELIVERED = 0
EXIT_NODE_FAILED = 10
EXIT_TIMEOUT_MANUAL = 11
EXIT_ROUNDS_EXHAUSTED = 12
EXIT_TOTAL_TIMEOUT = 13
EXIT_CONFIG = 20

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

# GRAPH.md §2 的"可 grep 证据词"：日志里 branch= 的取值必须逐字取自这张表（图/日志/判定同源）
BRANCH_TOKENS = {
    "all_green_deliver": "B1",
    "node_failed_retry": "B2",
    "retries_exhausted": "B3",
    "node_timeout": "B4",
    "manual_escalation": "B4",
    "total_timeout": "B5",
    "rounds_exhausted": "B6",
    "spawn_failed": "B3",
}

VERDICT_EXIT = {
    "DELIVERED": EXIT_DELIVERED,
    "NODE_FAILED": EXIT_NODE_FAILED,
    "TIMEOUT_MANUAL": EXIT_TIMEOUT_MANUAL,
    "ROUNDS_EXHAUSTED": EXIT_ROUNDS_EXHAUSTED,
    "TOTAL_TIMEOUT": EXIT_TOTAL_TIMEOUT,
}


# --------------------------------------------------------------------------- 配置
def load_config(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} 不是 YAML mapping")
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise KeyError(f"config 缺少键: {', '.join(missing)}")
    return raw


def apply_overrides(cfg: dict, overrides: list[str]) -> list[tuple[str, object]]:
    """--set key=value：覆盖 config 键（同样记入日志与 resolved config，不引入隐藏阈值）。"""
    applied: list[tuple[str, object]] = []
    for item in overrides:
        if "=" not in item:
            raise KeyError(f"--set 需要 key=value，得到 {item!r}")
        key, _, text = item.partition("=")
        key = key.strip()
        if key not in REQUIRED_KEYS:
            raise KeyError(f"--set 未知键 {key!r}，合法键: {', '.join(REQUIRED_KEYS)}")
        value = yaml.safe_load(text)
        if key == "nodes":
            value = [str(v) for v in value]
        elif key in {"fail_nodes", "hang_nodes"}:
            value = [str(v) for v in (value or [])]
        elif key == "slow_nodes":
            value = dict(value or {})
        elif key in {"max_rounds", "max_retries"}:
            value = int(value)
        else:
            value = float(value)
        cfg[key] = value
        applied.append((key, value))
    return applied


def validate_config(cfg: dict) -> None:
    nodes = cfg["nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes 必须是非空列表")
    if len(set(nodes)) != len(nodes):
        raise ValueError(f"nodes 有重名: {nodes}")
    for key in ("per_node_timeout", "total_timeout", "node_work_seconds"):
        if float(cfg[key]) < 0:
            raise ValueError(f"{key} 不能为负")
    for key in ("max_rounds", "max_retries", "kill_grace_seconds", "poll_interval_seconds"):
        if float(cfg[key]) < 0:
            raise ValueError(f"{key} 不能为负")
    if int(cfg["max_rounds"]) < 1:
        raise ValueError("max_rounds 必须 >= 1")
    if float(cfg["poll_interval_seconds"]) <= 0:
        raise ValueError("poll_interval_seconds 必须 > 0")
    known = set(nodes)
    for key in ("fail_nodes", "hang_nodes"):
        unknown = [n for n in cfg[key] if n not in known]
        if unknown:
            raise ValueError(f"{key} 引用了不在 nodes 里的节点: {unknown}")
    unknown_slow = [n for n in dict(cfg["slow_nodes"]) if n not in known]
    if unknown_slow:
        raise ValueError(f"slow_nodes 引用了不在 nodes 里的节点: {unknown_slow}")


# ------------------------------------------------------------------- 节点状态
@dataclass
class NodeState:
    name: str
    index: int                      # 1 基序号 → shards/NN.json
    status: str = "pending"          # pending|dispatched|done_ok|done_fail|timeout|ok|failed|
                                     # retry_scheduled|total_timeout|rounds_exhausted
    attempts: int = 0
    exit_code: int | None = None
    artifact: str | None = None
    reason: str = ""
    branch: str = ""
    needs_human: bool = False
    last_duration_s: float = 0.0
    total_duration_s: float = 0.0
    attempt_log: list[dict] = field(default_factory=list)
    stderr_logs: list[str] = field(default_factory=list)

    @property
    def shard_name(self) -> str:
        return f"{self.index:02d}"


# ------------------------------------------------------------------- 编排主体
class Orchestrator:
    def __init__(self, config_path: Path, out: Path, overrides: list[str]) -> None:
        self.config_path = config_path.resolve()
        self.out = out.resolve()
        self.cfg = load_config(self.config_path)
        self.overridden = apply_overrides(self.cfg, overrides)
        validate_config(self.cfg)

        self.run_id = self.out.name
        (self.out / "shards").mkdir(parents=True, exist_ok=True)
        (self.out / "logs").mkdir(parents=True, exist_ok=True)
        self.resolved_config_path = self.out / "config.resolved.yaml"
        self.resolved_config_path.write_text(
            yaml.safe_dump(self.cfg, sort_keys=True, allow_unicode=True), encoding="utf-8"
        )
        self.worker_config_path = self.resolved_config_path

        self.log_path = self.out / "logs" / "orchestrator.log"
        self._log_fh = self.log_path.open("a", encoding="utf-8")

        self.states: dict[str, NodeState] = {
            name: NodeState(name=name, index=i + 1) for i, name in enumerate(self.cfg["nodes"])
        }
        self.start_mono = time.monotonic()
        self.start_epoch = time.time()
        self.total_timeout_hit = False
        self.rounds_used = 0
        self.round_attempts: list[dict] = []
        self.worker_path = (Path(__file__).resolve().parent / "worker.py")
        self.branch_counts: dict[str, int] = {}
        self.code_sha256 = self._code_fingerprint()

        self.log("ORCH_START", run_id=self.run_id, config=str(self.config_path),
                 resolved_config=str(self.resolved_config_path), out=str(self.out),
                 ppid=os.getppid(), python=sys.version.split()[0],
                 overrides=self.overridden or "none",
                 orchestrator_sha256=self.code_sha256["orchestrator.py"],
                 worker_sha256=self.code_sha256["worker.py"])
        for key in REQUIRED_KEYS:
            self.log("CONFIG_LOADED", key=key, value=self.cfg[key])
        self.log("CONFIG_CONTRACT", required_keys=list(REQUIRED_KEYS),
                 required_key_count=len(REQUIRED_KEYS),
                 missing_keys="none",
                 note="缺任一 required key → 退出码 20，不补默认值")

    # ------------------------------------------------------------------ 日志
    def log(self, event: str, **fields) -> None:
        # 分支命中计数与日志同源：每写出一条 branch= 证据行，计数就 +1（REPORT 只报真实命中）
        token = fields.get("branch")
        if isinstance(token, str) and token in BRANCH_TOKENS:
            self.branch_counts[token] = self.branch_counts.get(token, 0) + 1
        parts = [f"{time.time():.3f}", f"pid={os.getpid()}", "role=orchestrator", f"event={event}"]
        for key, value in fields.items():
            if isinstance(value, (dict, list, tuple)):
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                text = str(value)
            if any(c.isspace() for c in text):  # 带空格的值加引号，保证 key=value 可被机器切分
                text = '"' + text + '"'
            parts.append(f"{key}={text}")
        self._log_fh.write(" ".join(parts) + "\n")
        self._log_fh.flush()
        os.fsync(self._log_fh.fileno())

    def elapsed_s(self) -> float:
        return round(time.monotonic() - self.start_mono, 3)

    def _code_fingerprint(self) -> dict[str, str]:
        """产出本 run 的代码版本指纹（D1：产物必须能追溯到具体代码版本）。"""
        here = Path(__file__).resolve().parent
        out = {}
        for name in ("orchestrator.py", "worker.py"):
            path = here / name
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "missing"
        return out

    @staticmethod
    def _rel(path: Path | None) -> str:
        return str(path) if path else "—"

    # ------------------------------------------------------------------ fan-out
    def dispatch(self, node_names: list[str], round_no: int) -> dict[str, dict]:
        """★ fan-out：每个节点一个独立子进程，Popen 之间不做任何 wait/join。"""
        active: dict[str, dict] = {}
        dispatch_t0 = time.monotonic()
        for name in node_names:
            state = self.states[name]
            state.attempts += 1
            state.status = "dispatched"
            cmd = [
                sys.executable, str(self.worker_path),
                "--node", name,
                "--config", str(self.worker_config_path),
                "--round", str(round_no),
                "--out", str(self.out),
            ]
            try:
                # 每次尝试的 worker stderr 单独落盘（§4 契约：报错必须有落盘位，不许被吞）
                err_rel = f"logs/worker-{state.shard_name}.round{round_no}.err"
                err_fh = (self.out / err_rel).open("wb")
                try:
                    # ★ 连续 Popen，之间没有 wait()/join()：这就是 fan-out
                    proc = subprocess.Popen(cmd, stderr=err_fh)
                finally:
                    err_fh.close()  # 子进程已持有该 fd；父进程不必继续占着
            except OSError as exc:  # 起进程失败 = 节点挂，如实传播（不吞成成功）
                state.status = "failed"
                state.reason = f"spawn_failed: {exc!r}"
                state.branch = "spawn_failed(no retry)"
                state.exit_code = None
                state.stderr_logs.append(err_rel)
                self.log("BRANCH", node=name, round=round_no, branch="spawn_failed",
                         status="failed", reason=state.reason, worker_err=err_rel)
                continue
            deadline = time.monotonic() + float(self.cfg["per_node_timeout"])
            state.stderr_logs.append(err_rel)
            active[name] = {
                "node": name,
                "proc": proc,
                "pid": proc.pid,
                "round": round_no,
                "cmd": cmd,
                "t_dispatch_mono": time.monotonic(),
                "t_dispatch_epoch": round(time.time(), 3),
                "deadline_mono": deadline,
                "terminated": False,
                "killed": False,
                "stderr_log": err_rel,
            }
            self.log("DISPATCH", node=name, round=round_no, pid=proc.pid,
                     attempt=state.attempts, worker=str(self.worker_path),
                     per_node_timeout=self.cfg["per_node_timeout"],
                     deadline_epoch=round(time.time() + float(self.cfg["per_node_timeout"]), 3),
                     worker_err=err_rel,
                     cmd=" ".join(cmd))
        span_ms = round((time.monotonic() - dispatch_t0) * 1000, 3)
        pids = [info["pid"] for info in active.values()]
        self.log("FANOUT_DONE", round=round_no, pids=pids, nodes=list(active.keys()),
                 dispatch_count=len(active), dispatch_span_ms=span_ms,
                 note="no wait() between Popen calls")
        return active

    # ------------------------------------------------------------------ collect (fan-in)
    def collect(self, active: dict[str, dict]) -> bool:
        """轮询等待各进程：exit code 即成败；per_node_timeout 到点 terminate/kill。

        返回 True 表示 total_timeout 命中（触发退出条件）。
        轮询顺序：先收已退出的（避免误杀刚完成的节点）→ 再查总预算 → 再处理单节点超时。
        """
        total_deadline = self.start_mono + float(self.cfg["total_timeout"])
        poll = float(self.cfg["poll_interval_seconds"])

        while active:
            for name, info in list(active.items()):
                rc = info["proc"].poll()
                if rc is not None:
                    self._finish_process(name, info, rc)
                    del active[name]
            if not active:
                break

            now = time.monotonic()
            if now >= total_deadline:
                self.total_timeout_hit = True
                self.log("BRANCH", branch="total_timeout",
                         total_timeout=self.cfg["total_timeout"],
                         elapsed_s=self.elapsed_s(),
                         still_running=[self._desc(i) for i in active.values()],
                         reason="elapsed >= total_timeout → 触发退出条件")
                for name, info in list(active.items()):
                    self._stop(info, reason="total_timeout")
                    self._finish_total_timeout(name, info)
                active.clear()
                return True

            for name, info in list(active.items()):
                if now >= info["deadline_mono"]:
                    over = round(now - info["deadline_mono"], 3)
                    self.log("BRANCH", node=name, round=info["round"], branch="node_timeout",
                             per_node_timeout=self.cfg["per_node_timeout"],
                             overdue_s=over, pid=info["pid"],
                             reason="still running past per_node_timeout → 超时分支")
                    self._stop(info, reason="per_node_timeout")
                    final_rc = info["proc"].poll()
                    if final_rc is None:
                        try:
                            final_rc = info["proc"].wait(
                                timeout=float(self.cfg["kill_grace_seconds"]))
                        except subprocess.TimeoutExpired:
                            final_rc = -9
                    self._finish_timeout(name, info, final_rc)
                    del active[name]

            if active:
                time.sleep(poll)
        return False

    def _desc(self, info: dict) -> str:
        return f"{info['proc'].pid}@{info.get('round')}"

    def _stop(self, info: dict, reason: str) -> None:
        """terminate →（kill_grace_seconds 宽限）→ kill。"""
        grace = float(self.cfg["kill_grace_seconds"])
        proc = info["proc"]
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            self.log("PROC_TERMINATE", node=info.get("node", "?"), pid=info["pid"],
                     reason=reason, grace_s=grace)
            info["terminated"] = True
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            info["killed"] = True
            self.log("PROC_KILL", node=info.get("node", "?"), pid=info["pid"],
                     reason=f"{reason} and survived terminate by more than kill_grace_seconds={grace}")
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
        except OSError as exc:
            self.log("PROC_STOP_ERROR", pid=info["pid"], reason=repr(exc))

    def _finish_process(self, name: str, info: dict, rc: int) -> None:
        state = self.states[name]
        duration = round(time.monotonic() - info["t_dispatch_mono"], 3)
        state.last_duration_s = duration
        state.total_duration_s = round(state.total_duration_s + duration, 3)
        state.exit_code = rc
        rel_shard = f"shards/{state.shard_name}.json"
        shard_abs = self.out / rel_shard
        attempt = {
            "round": info["round"], "pid": info["pid"], "exit_code": rc,
            "duration_s": duration, "started_at_epoch": info["t_dispatch_epoch"],
            "terminated": info["terminated"], "killed": info["killed"],
            "worker_log": f"logs/worker-{state.shard_name}.round{info['round']}.log",
            "worker_err": info.get("stderr_log", "—"),
        }
        if rc == 0:
            ok, why = self._verify_shard(shard_abs, info, round_no=info["round"])
            if ok:
                state.status = "done_ok"
                state.artifact = rel_shard
                state.reason = "exit 0, shard verified"
            else:
                # 反假成功：退出码 0 但产物缺失/不属于本次尝试 = 不认
                state.status = "done_fail"
                state.artifact = None
                state.reason = f"integrity failure: exit 0 but {why}"
                attempt["integrity"] = why
        else:
            state.status = "done_fail"
            state.artifact = None
            state.reason = f"exit {rc} (worker reported failure)"
        state.attempt_log.append(attempt)
        self.round_attempts.append({"node": name, "duration_s": duration})
        self.log("NODE_DONE", node=name, round=info["round"], pid=info["pid"], exit_code=rc,
                 status=state.status, duration_s=duration,
                 artifact=state.artifact or "none", reason=state.reason,
                 worker_log=f"logs/worker-{state.shard_name}.round{info['round']}.log",
                 worker_err=info.get("stderr_log", "—"))

    def _verify_shard(self, shard_abs: Path, info: dict, round_no: int) -> tuple[bool, str]:
        """产物必须存在且属于本次尝试（防"上一轮的旧产物冒充本轮成功"）。"""
        if not shard_abs.exists():
            return False, f"artifact {shard_abs.relative_to(self.out)} missing"
        try:
            payload = json.loads(shard_abs.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return False, f"artifact {shard_abs.name} unreadable: {exc!r}"
        if payload.get("round") != round_no:
            return False, f"artifact {shard_abs.name} round={payload.get('round')} != {round_no}"
        if payload.get("pid") != info["pid"]:
            return False, f"artifact {shard_abs.name} pid={payload.get('pid')} != {info['pid']}"
        return True, "ok"

    def _finish_timeout(self, name: str, info: dict, rc: int | None) -> None:
        state = self.states[name]
        duration = round(time.monotonic() - info["t_dispatch_mono"], 3)
        state.last_duration_s = duration
        state.total_duration_s = round(state.total_duration_s + duration, 3)
        state.status = "timeout"
        state.exit_code = rc
        state.artifact = None
        state.needs_human = True
        state.reason = (f"no exit within per_node_timeout={self.cfg['per_node_timeout']}s; "
                        f"terminate={info['terminated']} kill={info['killed']} final_exit={rc}")
        state.attempt_log.append({
            "round": info["round"], "pid": info["pid"], "exit_code": rc, "duration_s": duration,
            "timeout": True, "terminated": info["terminated"], "killed": info["killed"],
            "worker_log": f"logs/worker-{state.shard_name}.round{info['round']}.log",
            "worker_err": info.get("stderr_log", "—"),
        })
        self.round_attempts.append({"node": name, "duration_s": duration})
        self.log("BRANCH", node=name, round=info["round"], branch="manual_escalation",
                 status="timeout", needs_human=True, per_node_timeout=self.cfg["per_node_timeout"],
                 pid=info["pid"], duration_s=duration,
                 reason="超时不走自动重试：进程仍存活，需人工看现场（日志/shard 缺失）")
        self.log("NODE_DONE", node=name, round=info["round"], pid=info["pid"], exit_code=rc,
                 status="timeout", duration_s=duration, artifact="none", reason=state.reason,
                 worker_log=f"logs/worker-{state.shard_name}.round{info['round']}.log",
                 worker_err=info.get("stderr_log", "—"))

    def _finish_total_timeout(self, name: str, info: dict) -> None:
        state = self.states[name]
        duration = round(time.monotonic() - info["t_dispatch_mono"], 3)
        state.last_duration_s = duration
        state.total_duration_s = round(state.total_duration_s + duration, 3)
        state.status = "total_timeout"
        state.artifact = None
        state.exit_code = info["proc"].poll()
        state.reason = (f"aborted at total_timeout={self.cfg['total_timeout']}s "
                        f"(elapsed={self.elapsed_s()}s)")
        state.branch = "total_timeout(exit condition)"
        state.attempt_log.append({
            "round": info["round"], "pid": info["pid"], "exit_code": state.exit_code,
            "duration_s": duration, "aborted_by": "total_timeout",
            "worker_log": f"logs/worker-{state.shard_name}.round{info['round']}.log",
            "worker_err": info.get("stderr_log", "—"),
        })
        self.log("NODE_DONE", node=name, round=info["round"], pid=info["pid"],
                 exit_code=state.exit_code, status="total_timeout", duration_s=duration,
                 artifact="none", reason=state.reason,
                 worker_log=f"logs/worker-{state.shard_name}.round{info['round']}.log",
                 worker_err=info.get("stderr_log", "—"))
        # 被总超时中止的尝试同样计入 PARALLEL_EVIDENCE 的 sum_attempt_s（否则该行会退化成 0）
        self.round_attempts.append({"node": name, "duration_s": duration})

    # ------------------------------------------------------------------ 分支判定
    def decide_branches(self, round_no: int) -> None:
        max_retries = int(self.cfg["max_retries"])
        for name, state in self.states.items():
            if state.status == "done_ok":
                state.status = "ok"
                state.branch = "all_green_deliver"
                self.log("BRANCH", node=name, round=round_no, branch=state.branch,
                         status="ok", attempts=state.attempts)
            elif state.status == "done_fail":
                retries_used = max(state.attempts - 1, 0)
                max_rounds = int(self.cfg["max_rounds"])
                rounds_left = max_rounds - round_no
                if retries_used < max_retries and rounds_left <= 0:
                    # 还有重试预算，但轮次上界已到：不能假装"下一轮再跑"，直接落 B6 退出条件
                    state.status = "rounds_exhausted"
                    state.needs_human = True
                    state.branch = "rounds_exhausted(exit condition)"
                    self.log("BRANCH", node=name, round=round_no, branch="rounds_exhausted",
                             status="rounds_exhausted", max_rounds=max_rounds,
                             retries_used=retries_used, max_retries=max_retries,
                             retries_remaining=max_retries - retries_used,
                             reason=f"重试预算还剩 {max_retries - retries_used} 次但 round={round_no} 已是 "
                                    f"max_rounds={max_rounds} → 触发退出条件（不谎报还会重试）")
                elif retries_used < max_retries:
                    state.status = "retry_scheduled"
                    state.branch = f"node_failed_retry({retries_used + 1}/{max_retries})"
                    self.log("BRANCH", node=name, round=round_no, branch="node_failed_retry",
                             status="retry_scheduled", retries_used=retries_used + 1,
                             max_retries=max_retries, reason=state.reason)
                else:
                    state.status = "failed"
                    state.branch = f"retries_exhausted(max_retries={max_retries})"
                    self.log("BRANCH", node=name, round=round_no, branch="retries_exhausted",
                             status="failed", retries_used=retries_used, max_retries=max_retries,
                             reason=state.reason)
            elif state.status == "timeout":
                state.branch = "manual_escalation(no auto retry)"

    def all_green(self) -> bool:
        return all(s.status == "ok" for s in self.states.values())

    # ------------------------------------------------------------------ 主循环
    def run(self) -> int:
        max_rounds = int(self.cfg["max_rounds"])
        self.log("LOOP_BEGIN", max_rounds=max_rounds, total_timeout=self.cfg["total_timeout"],
                 per_node_timeout=self.cfg["per_node_timeout"],
                 max_retries=self.cfg["max_retries"], nodes=list(self.cfg["nodes"]))
        for round_no in range(1, max_rounds + 1):
            pending = [n for n, s in self.states.items()
                       if s.status in ("pending", "retry_scheduled")]
            if not pending:
                self.log("LOOP_EXIT", round=round_no, reason="no pending nodes")
                break
            if time.monotonic() >= self.start_mono + float(self.cfg["total_timeout"]):
                self.total_timeout_hit = True
                self.log("BRANCH", branch="total_timeout", where="before_dispatch",
                         elapsed_s=self.elapsed_s(), pending=pending,
                         reason="触发退出条件：total_timeout 用尽，未派发剩余节点")
                for name in pending:
                    state = self.states[name]
                    state.status = "total_timeout"
                    state.reason = f"never dispatched: total_timeout={self.cfg['total_timeout']}s"
                    state.branch = "total_timeout(exit condition)"
                break

            self.rounds_used = round_no
            self.log("ROUND_BEGIN", round=round_no, round_limit=max_rounds,
                     pending=pending, pending_count=len(pending))
            round_t0 = time.monotonic()
            self.round_attempts = []
            active = self.dispatch(pending, round_no)
            dispatch_pids = [i["pid"] for i in active.values()]
            if not active:
                self.log("ROUND_END", round=round_no, reason="no process dispatched")
                self.decide_branches(round_no)
                continue
            total_hit = self.collect(active)
            round_wall = round(time.monotonic() - round_t0, 3)
            sum_attempt = round(sum(a["duration_s"] for a in self.round_attempts), 3)
            self.log("PARALLEL_EVIDENCE", round=round_no, pids=dispatch_pids,
                     node_count=len(dispatch_pids), round_wall_s=round_wall,
                     sum_attempt_s=sum_attempt,
                     concurrent=len(dispatch_pids) > 1 and round_wall < sum_attempt,
                     note="all Popen issued before first poll/wait; wall < sum(attempt) ⇒ 真并行")
            if total_hit:
                break
            self.decide_branches(round_no)

        if not self.total_timeout_hit:
            max_retries = int(self.cfg["max_retries"])
            stranded = [n for n, s in self.states.items()
                        if s.status in ("pending", "retry_scheduled", "dispatched")]
            for name in stranded:
                state = self.states[name]
                state.status = "rounds_exhausted"
                state.needs_human = True
                state.reason = (f"rounds exhausted at max_rounds={max_rounds} while node "
                                f"not ok (retries_used={max(state.attempts - 1, 0)}/"
                                f"{max_retries})")
                state.branch = "rounds_exhausted(exit condition)"
                self.log("BRANCH", node=name, branch="rounds_exhausted",
                         max_rounds=max_rounds, status="rounds_exhausted",
                         reason=state.reason)
            exhausted = [n for n, s in self.states.items() if s.status == "rounds_exhausted"]
            if exhausted:
                self.log("LOOP_EXIT", round=self.rounds_used, reason="rounds_exhausted",
                         max_rounds=max_rounds, stranded=exhausted,
                         note="轮次上界命中且仍有节点未 ok → 触发退出条件（GRAPH B6，退出码 12）")

        verdict, exit_code = self.verdict()
        self.write_report(verdict, exit_code)
        self.write_state(verdict, exit_code)
        self.log("FINAL_EXIT", verdict=verdict, exit_code=exit_code,
                 rounds_used=self.rounds_used, wall_s=self.elapsed_s(),
                 report=str(self.out / "REPORT.md"))
        self._log_fh.close()
        return exit_code

    def verdict(self) -> tuple[str, int]:
        statuses = {s.status for s in self.states.values()}
        if "total_timeout" in statuses:
            verdict = "TOTAL_TIMEOUT"
        elif "timeout" in statuses:
            verdict = "TIMEOUT_MANUAL"
        elif "failed" in statuses:
            verdict = "NODE_FAILED"
        elif "rounds_exhausted" in statuses:
            verdict = "ROUNDS_EXHAUSTED"
        elif statuses == {"ok"}:
            verdict = "DELIVERED"
        else:
            verdict = "NODE_FAILED"
        return verdict, VERDICT_EXIT[verdict]

    # ------------------------------------------------------------------ 产物
    def write_report(self, verdict: str, exit_code: int) -> None:
        cfg = self.cfg
        lines = [
            f"# REPORT — run `{self.run_id}`",
            "",
            f"- verdict: **{verdict}**",
            f"- 主流程退出码: **{exit_code}**",
            f"- 交付判定: {'✅ 全绿交付' if exit_code == 0 else '❌ 不交付（失败已传播，不报假成功）'}",
            f"- config: `{self.config_path.name}` → 生效值落盘 `config.resolved.yaml`",
            f"- 生效阈值: nodes={list(cfg['nodes'])} node_work_seconds={cfg['node_work_seconds']} "
            f"per_node_timeout={cfg['per_node_timeout']} total_timeout={cfg['total_timeout']} "
            f"max_rounds={cfg['max_rounds']} max_retries={cfg['max_retries']} "
            f"kill_grace_seconds={cfg['kill_grace_seconds']} "
            f"poll_interval_seconds={cfg['poll_interval_seconds']} "
            f"fail_nodes={list(cfg['fail_nodes'])} slow_nodes={dict(cfg['slow_nodes'])} "
            f"hang_nodes={list(cfg['hang_nodes'])}",
            f"- 覆盖的键: {self.overridden if self.overridden else '无（全用 config.yaml 默认值）'}",
            f"- 编排墙钟: {self.elapsed_s()}s，派发轮次: {self.rounds_used}/"
            f"{cfg['max_rounds']}（orchestrator pid 见 logs/orchestrator.log 首行）",
            "- 日志: `logs/orchestrator.log` + `logs/worker-NN.roundR.log` + "
            "`logs/worker-NN.roundR.err`（worker stderr 原文，成功节点为 0 字节）",
            f"- 代码版本指纹: orchestrator.py={self.code_sha256['orchestrator.py']} "
            f"worker.py={self.code_sha256['worker.py']}（同 state.json.code_sha256）",
            "- 耗时口径: 下表 `duration_s` 是 **orchestrator 侧墙钟**（含 Popen 派发开销）；"
            "worker 自计的跑分耗时见 `shards/NN.json` 的 `duration_s`，两者相差约 0.1s 属正常",
            "",
            "## 节点结果（每节点一行：状态 + 产物引用 + 耗时）",
            "",
            "| # | node | status | attempts | artifact | duration_s | exit_code | needs_human | reason | branch |",
            "|---|------|--------|----------|----------|------------|-----------|-------------|--------|--------|",
        ]
        for state in self.states.values():
            lines.append(
                f"| {state.index} | {state.name} | **{state.status}** | {state.attempts} | "
                f"{state.artifact or '—'} | {state.last_duration_s} | "
                f"{state.exit_code if state.exit_code is not None else '—'} | "
                f"{state.needs_human} | {state.reason or '—'} | {state.branch or '—'} |"
            )
        lines += ["", "## 尝试明细（每一次 Popen 一行：重试分支 / 强杀路径的证据）", "",
                  "| node | round | pid | exit_code | duration_s | terminated | killed | worker_log | worker_err |",
                  "|------|-------|-----|-----------|------------|------------|--------|------------|------------|"]
        for state in self.states.values():
            for attempt in state.attempt_log:
                lines.append(
                    f"| {state.name} | {attempt['round']} | {attempt['pid']} | "
                    f"{attempt.get('exit_code', '—')} | {attempt.get('duration_s')} | "
                    f"{bool(attempt.get('terminated'))} | {bool(attempt.get('killed'))} | "
                    f"`{attempt.get('worker_log', '—')}` | `{attempt.get('worker_err', '—')}` |"
                )
        manual = [s for s in self.states.values() if s.needs_human]
        lines += ["", "## 人工分支（timeout / rounds_exhausted）", ""]
        if manual:
            for state in manual:
                lines.append(
                    f"- **{state.name}** status={state.status} branch={state.branch}：{state.reason}；"
                    f"人工介入方式：看 `logs/worker-{state.shard_name}.round*.log` 里 "
                    f"`event=SIGNAL_RECEIVED` 与 `logs/worker-{state.shard_name}.round*.err`，"
                    f"再决定重跑或换机（本节点**没有**被自动重试）"
                )
        else:
            lines.append("- 无人工分支：本 run 没有任何 `needs_human=True` 节点"
                         "（`grep -c 'needs_human=True' logs/orchestrator.log` = "
                         f"{self.branch_counts.get('manual_escalation', 0) + self.branch_counts.get('rounds_exhausted', 0)}）")
        # 分支命中计数与日志同源（log() 每写出一条 branch= 证据行就 +1）：
        # 本表只报真实命中的分支，并显式列出没走到的分支，避免静态说明文字被当成"已验证"。
        lines += ["", "## 分支命中计数（与 logs/orchestrator.log 的 branch= 行同源）", "",
                  "| GRAPH 分支 | 证据词（可 grep） | 本 run 命中 |",
                  "|------------|-------------------|-------------|"]
        taken: list[str] = []
        for token, b_id in BRANCH_TOKENS.items():
            n = self.branch_counts.get(token, 0)
            if n:
                taken.append(token)
            lines.append(f"| {b_id} | `branch={token}` | {n if n else '—'} |")
        not_taken = [t for t in BRANCH_TOKENS if t not in self.branch_counts]
        lines += ["",
                  f"- 本 run **走到**的分支证据词：{', '.join(f'`{t}`' for t in taken) if taken else '（无）'}",
                  f"- 本 run **没走到**的分支证据词：{', '.join(f'`{t}`' for t in not_taken) if not_taken else '（无）'}"
                  " —— 没走到就是没走到，本文件不对它们下任何结论",
                  "",
                  "## 判定口径", "",
                  f"- 口径的唯一来源是 `GRAPH.md` §2（分支表）/ §5（阈值映射）/ §6（不变式）/ §7（场景清单）；"
                  "本文件不新增判据，只落盘本 run 的事实。",
                  f"- 本 run 的判定链：worker 退出码 → 节点 status"
                  f"（{', '.join(f'{s.name}={s.status}' for s in self.states.values())}）"
                  f" → verdict={verdict} → 主流程退出码 {exit_code}。",
                  "- 复核入口（不读 Python 代码即可判）："
                  "`logs/orchestrator.log` 的 `event=` 行 + 上两张表 + `state.json`。", ""]
        (self.out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    def write_state(self, verdict: str, exit_code: int) -> None:
        payload = {
            "run_id": self.run_id,
            "verdict": verdict,
            "exit_code": exit_code,
            "orchestrator_pid": os.getpid(),
            "config_file": str(self.config_path),
            "resolved_config": str(self.resolved_config_path),
            "effective_config": self.cfg,
            "overridden_keys": [{"key": k, "value": v} for k, v in self.overridden],
            "code_sha256": self.code_sha256,
            "branch_evidence_counts": {
                token: self.branch_counts.get(token, 0) for token in BRANCH_TOKENS
            },
            "wall_s": self.elapsed_s(),
            "rounds_used": self.rounds_used,
            "total_timeout_hit": self.total_timeout_hit,
            "report": str(self.out / "REPORT.md"),
            "orchestrator_log": str(self.log_path),
            "nodes": [
                {
                    "node": s.name, "index": s.index, "status": s.status,
                    "attempts": s.attempts, "exit_code": s.exit_code,
                    "artifact": s.artifact, "duration_s": s.last_duration_s,
                    "total_duration_s": s.total_duration_s, "needs_human": s.needs_human,
                    "reason": s.reason, "branch": s.branch, "attempts_detail": s.attempt_log,
                }
                for s in self.states.values()
            ],
        }
        (self.out / "state.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="3 节点 GPU 测试编排（子进程模拟 GPU 测试机）")
    ap.add_argument("--config", default="config.yaml", help="阈值唯一来源（GRAPH.md §5）")
    ap.add_argument("--out", default=None,
                    help="run 产物目录，默认 runs/<场景或 default>-<时间戳>")
    ap.add_argument("--scenario", default="default", help="场景名，用于 run_id 与日志")
    ap.add_argument("--set", dest="overrides", action="append", default=[],
                    metavar="KEY=VALUE", help="覆盖单个 config 键（回显在日志与 resolved config）")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[orchestrator] config 不存在: {config_path}", file=sys.stderr)
        return EXIT_CONFIG
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    out = Path(args.out) if args.out else Path("runs") / f"{args.scenario}-{stamp}"
    try:
        orch = Orchestrator(config_path, out, args.overrides)
    except Exception as exc:  # 配置问题：编排没起来，如实退出 20（不吞成成功）
        print(f"[orchestrator] 配置错误: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    exit_code = orch.run()
    report = orch.out / "REPORT.md"
    print(f"[orchestrator] verdict={orch.verdict()[0]} exit_code={exit_code} "
          f"report={report} log={orch.log_path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
