# 对比实验报告:mini-swe-agent GPU hang 诊断 —— 无 skill vs 注入 rocm-doctor skill

日期:2026-11-10 | 环境:D-002-G2-gfx1151(AMD Strix Halo gfx1151,WSL2 6.18.33.2-microsoft-standard-WSL2)
模型(两次一致):`Qwen Model ZX_only` @ `http://172.31.0.3:4000/v1`(LiteLLM 网关)
代理执行方式:mini SshEnvironment(所有命令经 SSH 在 WSL2 内执行,远端零安装)

## 1. 实验设计

- 同一任务提示词、同一模型、同一 40 步上限;崩溃现场只读诊断(禁改系统、禁重跑 GPU 负载)。
- **唯一变量**:Run B 的 system prompt 注入 AMD 官方 `rocm-doctor` 技能全文(SKILL.md 14.8KB + reference.md 16.1KB,共 ~31KB);Run A 使用 mini 默认 system prompt(62 字节)。
- 真值参照:现场目录 `VERDICT`(=REPRODUCED)、`signature_1.txt`(4 行规范签名)、`rc_1.txt`(rc=134)。
- 注意:两次运行都能读到真值文件(现场内含),因此对比重点在**诊断过程与报告质量**,而非"能否猜中答案"。

## 2. 结果对照

| 维度 | Run A(无 skill) | Run B(注入 rocm-doctor) |
|---|---|---|
| VERDICT 判定 | **REPRODUCED** ✓ 与真值一致 | **REPRODUCED** ✓ 与真值一致 |
| 模型调用次数 | 18 | 22 |
| 总 tokens | **202,436**(prompt 198.8K + completion 3.6K) | **487,717**(prompt 485.7K + completion 2.0K),≈ **2.4×** |
| 墙钟时间 | 189 s | 142 s *(两轮并行跑,受网关排队影响,仅供参考)* |
| system prompt | 62 B | 31,247 B(每轮对话重复携带) |
| 签名覆盖 | bench_1.log 5 行(1068/1072/1074/1077/1078),与规范签名几乎完全重合 | bench_1.log 3 处(1068/1072–1073/1077)+ **跨层补充 dmesg_after 685–690(dxgkio_escape ×6, -75)与 731–732(SIGABRT signal 6)** |
| 根因定位 | 批次 63 librocdxg 1.1.0 + libhsa 1.21.0 在 WSL2 dxg 通路上的内存 aperture 校验缺陷;KV cache 分配期间越界 → 队列 hang → FaultMonitor 触发 → abort(134) | 同一组件归因;额外给出双重候选解释:(A) HSA 地址翻译回归 (B) ggml HIP 后端地址计算,并关联 WSL2 dxgk 层 ioctl 失败 |
| 下一步建议 | 4 条(报 bug / 回退 61 基线验证 / llama.cpp 边界检查 / 裸机 vs WSL2 隔离) | 4 条且更具体(63 vs 61 二分并附 .so 文件大小、上游 issue 标签 gfx1151/WSL2/memory_aperture_violation、核对 llama.cpp f2cc728、小模型 KV 阈值测试) |

## 3. 诊断路径差异

- **Run A(直奔型)**:`cat VERDICT/signature_1.txt` → bench_1.log 崩溃段 → dmesg 前后 diff(dxg 行)→ rocminfo → 构建日志 → 复核 bench 上下文 → 提交。18 步内闭环。
- **Run B(系统扫描型)**:同样先读真值文件,随后按更全面的清单推进:dmesg before/after 各自全量关键词扫描 → rocminfo Agent/Pool 内存池 → md5/hipcc/cmake/git_clone 溯源 → `grep -c dxgkio_escape` 前后定量对比 → dmesg 680–720 段精读(发现 weston segfault、dxg ioctl 失败、llama-bench signal 6)。22 步。

## 4. 关键差异与解读

1. **结论正确性:两者打平**——VERDICT 与根因组件归因均与真值一致。
2. **证据广度:B 胜**——B 的签名/证据链跨到了 host 侧 dmesg(dxgkio_escape -75、SIGABRT signal 6),构成"GPU hang ↔ WSL2 直通层响应 ↔ 用户态 abort"三层闭环;A 的证据基本限于 bench_1.log + 单次 dmesg diff,且把 dxgkio_escape 判为"无关背景噪音"。
3. **解释分歧点**:dxgkio_escape(-75)发生于 1627s,llama-bench abort 在 1987s。A 视为噪音,B 视为"hang 的宿主侧响应"。两者都属推测,但 B 主动做了跨源时间轴关联,更符合 rocm-doctor 的方法论(先取证、再归因、明确假设分支 A/B)。
4. **成本:B 显著更贵**——prompt tokens 2.4×(31KB skill × 22 轮)。若任务简单且现场信息密集(如本次),skill 的边际收益主要在**证据广度与报告结构**,而非结论本身。
5. **行为风格:B 更"守规矩"**——rocm-doctor 的 scope gate / 只读约束被严格遵守,报告结构清晰分节(A 亦遵守约束,结构同样完整)。

## 5. 结论

在本场景(现场证据充分、根因可从日志直接读出)下,注入 rocm-doctor skill:
- **没有改变最终判定**(两者都正确得出 REPRODUCED 与组件级根因);
- **显著提升了取证广度与证据链层次**(跨 bench/dmesg/用户态 signal 三层关联,建议更可执行);
- **代价是约 2.4 倍的 token 消耗与略多的步数**。

适用建议:现场信息稀疏、需要跨层取证的复杂故障 → 注入 skill 收益大;日志自解释的简单复现判定 → 基线已足够。

## 6. 产物清单

- 轨迹(含完整对话/命令/token):`/home/zs/gpu_hang_exp/trajectories/runA.json`、`runB.json`
- 终端日志:`/home/zs/gpu_hang_exp/logs/runA.log`、`runB.log`
- 两份原始报告:`/home/zs/gpu_hang_exp/reports/runA_report.md`、`runB_report.md`
- 实验资产:`/home/zs/gpu_hang_exp/`(task.txt 冻结任务、exp_base.yaml、runB.yaml、ssh_env.py、extract.py)
