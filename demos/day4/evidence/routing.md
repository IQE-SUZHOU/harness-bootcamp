# Workflow routing trace

`tool-workflow/agent-start` 与 `tool-workflow/agent-end` 按 `(runId, agent.seq)` 配对；
`label` 是脚本里的路由键，`childId` 指向实际执行该分支的子会话。

| agent.seq | label | phase | childId | start seq | end seq | duration ms | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `ci` | fan-out | `1d2c1572-f8ba-45ce-885b-63c9fcb01374` | 21 | 24 | 2024 | `completed` |
| 2 | `cd` | fan-out | `4adf120c-cc19-47dc-b63a-168fb07c9aab` | 23 | 27 | 2235 | `completed` |
| 3 | `iac` | fan-out | `6bf3f30d-0a72-4c57-bb47-eb8c654b5092` | 26 | 28 | 2032 | `completed` |
| 4 | `summary` | fan-in | `245ef257-256f-42e5-9fcb-8ce4a3880d75` | 30 | 31 | 1383 | `completed` |

本次 run 的 `maxActive` = **2**，与 `maxConcurrentAgents: 2` 一致。

fan-in 屏障：`summary.startSeq` 大于 `ci`/`cd`/`iac` 的最大 `endSeq`，说明汇总 agent 在三个分支全部结束后才启动。
