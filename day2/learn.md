Day 02 学习进度

训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
日期：2026-11-06 · 分支：[YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH)

# 一、核心概念（今日课程）

- **State**：跨步骤需要记住的数据——任务进度、中间结果、配置；context 是"现在看到的"，state 是"记住的"，混在一起就会重复干活或丢信息
- **持久化**：把 state 写到文件，进程死了也不丢；真正的考点不是"存进去"，而是**写一半死了怎么办**（原子性）和**死前最后一刻文件里是什么**（可判定性）
- **Session 生命周期**：创建 → 运行 → 中断 → 恢复 → 结束。今天最有价值的认知：**interrupted 不是死前写进文件的**——进程被 kill -9 时来不及写任何东西，文件里只有"最后已知状态"，中断是恢复方推断出来的

```
created ──▶ running ──▶ interrupted ──▶ resumed ──▶ finished
             │              │
             │        推断出来的！文件里仍是 running
             └─ 每个阶段都能指到 state.json 的 session.status 字段
```

# 二、今日实践总结

今天的主线：**两层实验**。脚本层做一个 kill -9 安全的 state store；agent 层把 agent 会话本身当成"被 kill 的进程"，用 HANDOFF 文件做它的 state——两个版本互为印证。

## 1. 脚本版：双记录分工（快照 + 日志）

- `state.json` 快照：只存"最后已知状态"，tmp + os.replace 原子替换，kill -9 时读者永远看不到半截 JSON
- `events.jsonl` 日志：append-only + fsync，是**权威事实流**——快照可能滞后，日志不会
- 存/不存口诀：恢复时需要它才能继续 → 存；重启后能重算/重读/已失效 → 不存。原始输出存路径不存值，易失效缓存和密钥不进 state
- 恢复 = journal 回放对账，三条判定：journal 有 finished → SKIP；started 无 finished → RERUN（整任务重跑，不看产物"看起来完成几成"）；journal 沉默 → 才参考快照

## 2. agent 版 interrupt→resume（meta 实验）

- 指令里加硬性规则：agent **每完成一个任务必须先更新 `.agent/HANDOFF.md`**（任务清单/关键决策/下一步），落盘先于继续
- 会话 1 跑到 T3 手动停止（模拟 kill -9），`cat .agent/HANDOFF.md` 就是中断现场：T1✅ T2✅ T3⏳
- 会话 2 只喂一段 prompt："唯一信息来源是 HANDOFF.md 和现有文件，禁止问历史"——结果**没有重复做 T1/T2、没有重新设计文件结构**，从 T3 直接续
- 体会：**对话上下文 = context（易失），HANDOFF.md = state（可恢复）**。L05"跨会话上下文连续"和 L12"干净交接"亲手演了一遍：agent 的"落盘"不是自动的，要靠指令强制外置

## 3. 恢复的真正难点

不是把数据读回来，而是把"中断现场"修剪成**可判定**状态：半截产物、快照滞后、事件没闭合，都要有显式规则而不是靠猜。重跑必须幂等——digest 与 attempt/时间戳无关，重跑结果和首次一致才算恢复成功。

# 三、踩坑实录（今天的学费）

| 坑 | 教训 |
| --- | --- |
| `journal_path.relative_to(ROOT)` 在 run 目录指向仓库外时抛 ValueError | 路径运算假设了目录布局，加 rel() 回退绝对路径——辅助函数也要考虑边界 |
| demo.sh 校验段 TypeError：run_started 事件没有 generation 字段 | **每个事件的 schema 不同**，逐字段核对事件词表，别假设所有行同构 |
| 校验段 heredoc 里的 python 失败被吞，脚本照样打印"完成"并以 0 退出 | 校验步骤必须显式判退出码；`$?` 检查不能省，否则 fail 变成假 pass |
| demo.sh 建出来是 600 权限，`./demo.sh` 直接 permission denied | 交付物先过一遍"使用者视角"冒烟：能不能执行、能不能跑 |
| 下刀时机靠 sleep 猜，机器快慢导致 kill 落点漂移 | 改成**轮询 journal 等目标任务的 task_started 事件出现**再下刀——事件对齐代替时间猜测 |

# 四、验收数据

- 8/8 任务 done；journal 20 行、seq 连续单调；`task_started=9` vs `task_finished=8`，差的那 1 次正是被 kill 未闭合的尝试
- task-05 attempt=2，digest 与首次一致（**幂等可证**）；task-01..04 产物 mtime/md5 未变（**SKIP 可证**，不是靠肉眼看）
- 双下刀对照：task-05（stream 型，恢复前留 2/5 行半截产物）vs task-04（atomic 型，恢复前产物**不存在**）——副作用形状决定恢复现场的形状
- 三条防御实测：快照 done 但 journal 无 finished → 降级 RERUN；torn journal 行 → 坏行计数不致命；快照整体损坏 → 丢弃、全靠 journal 重建
- 空恢复分支：全 done 目录再 resume → skip=8 rerun=0，幂等退出
- agent 版：新会话零重复 T1/T2，HANDOFF 记录与磁盘现场一致

# 五、交付记录

| 交付物 | 内容 |
| --- | --- |
| `harness.py` | 任务 runner + 双记录 state store（fresh/resume/status 三态） |
| `resume.py` | journal 回放 + reconcile 对账（Decision 带 reason 证据链） |
| `demo.sh` | 一键演示：事件对齐下刀 → kill -9 → 恢复 → 6 段硬断言校验 |
| `STATE_DESIGN.md` | 设计说明：两记录分工 / 对账决策表 / 重跑语义 / 失败模式表 |
| `.agent/HANDOFF.md` | agent 会话的 state 文件 + 全过程进展记录 |
| 证据日志 | `demo-run.log`（task-05 下刀）、`demo-run-task04.log`（对照组）、`demo-run-final.log`（回归 diff 为空）、`evidence-t2/`（T2 中断现场备份） |

交付物已提交至 YZH 分支（本提交）

# 六、下一阶段内容（Day 03 预告）

核心概念：DoD（完成由可执行的验证定义）/ 验证门禁 / Maker-checker 分离 / 有限重试 + 人工 gate。

**衔接自评**：今天已经埋了 DoD 的雏形——demo.sh 的校验段全是硬断言（8/8 done、seq 单调、digest 一致），任一不过就 die，退出码非 0，这就是"完成由验证定义"而不是"我看着跑完了"。HANDOFF.md 的任务清单表本身就是交接清单。明天要补的是制度化：把"自己写校验自己"升级为独立 checker（只认验收标准不认实现叙述），给重试装上上限和人工升级 gate——正好可以拿今天这套对账决策表当被管对象：SKIP/RERUN 的判定规则，就是一份现成的"验收标准"。
