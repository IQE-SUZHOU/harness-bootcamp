# D4 Evidence Snapshot

Sanitized output of one passing `demos/day4/loop-graph-demo.sh` run. Raw
artifacts live in `d4-artifacts/` and are not committed.

| File | Content |
| --- | --- |
| `summary.json` | Machine-readable acceptance flags, five run results, routing trace, runtime facts, stop conditions, goal auto-loop config |
| `evidence.md` | Human-readable acceptance table, stop-condition table, goal layers, fan-out/fan-in JSON, failure table |
| `verifier-result.json` | Independent non-LLM verifier (V1–V13) |
| `routing.md` | Per-branch `agent.seq`, label, child session, start/end sequence, duration, outcome |
| `graph.mmd` | Mermaid graph of the three-way fan-out and fan-in summary |
| `stop-condition.json` | Effective `workflow-ptc` config after the overlay |
| `auto-loop.json` | Explicit `defaultMaxGoalRounds` and mounted goal layers |
| `fanout.json` | Fan-out/fan-in workflow call, script, meta, return value |
| `partial.json` | Ordinary branch failure → `[str, null, str]` |
| `fatal.json` | Illegal `agent()` option → whole-run error |
| `cap.json` | `maxTotalAgents: 2` → `AGENT_CAP` |
| `timeout.json` | `syncTimeoutMs: 3000` → script timeout |
| `<run>.events.json` | Paired `tool-workflow/*` events for that run |
| `<run>.runtime.json` | Permission preset, sandbox mode, approval policy, provider/model |
| `runtime.json` | Environment summary across all five sessions |

## Redaction

The demo redacts before writing this directory:

- the repository root becomes `<repo-root>`;
- the home directory becomes `<home>`;
- `DSH_HOME` becomes `<dsh-home>`;
- `sk-`-style tokens become `<api-key>`;
- only session IDs are kept for traceability; the session logs stay under
  `$DSH_HOME/sessions/` and are never copied here.

`verify_d4.py` scans every text file in this directory and fails V13 if an
absolute home path or an API-key-like token remains.

## Reproduction

```bash
# dsh must be on PATH; optional: export DSH_PATCH=/path/to/provider-patch.yml
cd <repo-root>
./demos/day4/loop-graph-demo.sh
```

The demo regenerates `d4-artifacts/` and overwrites every file here except this
README. Review `summary.json` first: `failures` must be empty, every
`acceptance` flag must be `true`, and `verifier-result.json.allPassed` must be
`true`.
