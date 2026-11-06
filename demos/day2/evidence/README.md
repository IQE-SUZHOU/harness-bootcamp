# Evidence snapshot

Sanitized output of one Day 2 demo run on **2026-11-06** with **dsh
0.2.0-rc.2**. Absolute paths were replaced with `<repo-root>` and the project
key with `<project-root-slug>`.

| File | Content |
| --- | --- |
| `evidence.md` | Pass/fail table for all 13 acceptance checks |
| `summary.json` | Machine-readable session ids, event counts, cache tokens, closers |
| `timeline-interrupted.txt` | Event timeline of the hard-killed session, ending at the open `job_output` call |
| `timeline-after-resume2.txt` | Same log after resume, showing the repair closers and the new turn |
| `resume1-final.txt` | Answer after a normal resume; it still knows the earlier question |
| `resume2-final.txt` | Answer after the crash resume; it acknowledges the interrupted call |

Regenerate with:

```bash
./demos/day2/interrupt-resume-demo.sh
```

Local output goes to the git-ignored `d2-artifacts/` directory. Session ids
and timings differ on every run; the check results and event order do not.
