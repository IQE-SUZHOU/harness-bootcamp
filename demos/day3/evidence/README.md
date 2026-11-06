# D3 Evidence Snapshot

Sanitized output of one passing `demos/day3/maker-checker-demo.sh` run. Raw
artifacts live in `d3-artifacts/` and are not committed.

| File | Content |
| --- | --- |
| `summary.json` | Machine-readable acceptance flags, checker results, verifier result, sessions, runtime config |
| `evidence.md` | Human-readable acceptance table, round-by-round checker details, todo table, fork-vs-spawn table |
| `verifier-baseline.json` | Non-LLM verifier on the pristine fixture |
| `verifier-final.json` | Non-LLM verifier after repairs and the human gate |
| `checker-baseline.json` | Blind spawn checker on the pristine fixture |
| `checker-fork-1.json` | Fork checker after the claim-only maker (must reject D2) |
| `checker-fork-*.json` | Fork checkers after each repair round |
| `checker-final-spawn.json` | Blind spawn checker after the human gate |
| `todo-summary.json` | `todo_write` writes, states seen, final items, blocked items |
| `fork-vs-spawn.json` | Child-session comparison: tool, provider, seeds, approval, first prompt |
| `runtime-config.json` | Permission preset, sandbox mode, approval policy, provider/model |
| `session-timeline.txt` | Maker session event timeline with `seq` |
| `protected-hashes.txt` | SHA-256 before/after for protected and demo files |
| `maker-report-initial.md` | The claim-only report (`7/7`) that the checker rejects |
| `maker-report-final.md` | The post-repair report |
| `claim-round-diff.txt` | Diff proving the claim round changed only `MAKER_REPORT.md` |
| `HUMAN_APPROVAL.forged.txt` | Present only if the maker forged the approval; the token is redacted |

## Redaction

The demo redacts before writing this directory:

- the human approval token becomes `<human-token>`;
- any fabricated `APPROVED-BY-HUMAN-...` value in maker reports is normalized to
  the same placeholder;
- the workspace path becomes `<workspace>`;
- the repository root becomes `<repo-root>`;
- the home directory becomes `<home>`;
- `DSH_HOME` becomes `<dsh-home>`.

No API keys, credentials, or machine-local session paths are committed.
`summary.json` records session IDs only for traceability; the corresponding raw
sessions stay under `$DSH_HOME/sessions/` and are not part of the repository.

## Reproduction

```bash
# dsh must be on PATH; optional: export DSH_PATCH=/path/to/provider-patch.yml
cd <repo-root>
./demos/day3/maker-checker-demo.sh
```

The demo regenerates `d3-artifacts/` and overwrites this directory. Review
`summary.json` first; `failures` must be empty and every `acceptance` flag must
be `true`.
