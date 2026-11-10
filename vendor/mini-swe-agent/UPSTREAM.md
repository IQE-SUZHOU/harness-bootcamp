# mini-SWE-agent — vendored snapshot(Day5 真实 harness demo)

- 上游:https://github.com/SWE-agent/mini-swe-agent
- 快照 commit:`04d809ceab9df28f9adaed044884180159172930`(2026-11-10,main)
- 许可证:MIT(见本目录 `LICENSE.md`)
- 取用范围:整仓(`src/`、`tests/`、`docs/` 等)
- 未取用:`.git/`、`.superpowers/`、`__pycache__/`

## 为什么放在这里

训练营 Day5 的 `swe/` 是按 mini-SWE-agent 思想手写的纯标准库教学版;
本目录是**真实的上游 mini-SWE-agent**,作为对照 demo:

1. 看"最小的真实 agent"长什么样:`src/minisweagent/agents/default.py`(主循环 ~180 行)、
   `models/litellm_model.py`、`environments/local.py`;
2. `gpu_hang_exp/` 是一次完整可复现的实战实验:**同一 GPU hang 诊断任务,
   无 skill vs 注入 AMD rocm-doctor skill 的对照运行**——
   含冻结任务 `task.txt`、SSH 执行环境 `exp_assets/ssh_env.py`(远端零安装跑 agent)、
   双份轨迹 `trajectories/*.json` 与对比报告 `reports/comparison.md`。

## 复现方式(任一机器可达 172.31.8.11 与 LLM 网关即可)

```bash
cd vendor/mini-swe-agent/gpu_hang_exp
export OPENAI_API_KEY=sk-...  OPENAI_API_BASE=http://172.31.0.3:4000/v1
export SSHPASS=<节点密码>  PYTHONPATH=$PWD
mini -c <pipx包内>/minisweagent/config/mini.yaml -c exp_base.yaml \
     -t "$(cat task.txt)" --output trajectories/runA.json -y --exit-immediately
# 注入 skill 版再加: -c runB.yaml
```
