# D2 interrupt → resume evidence

- repo: `<repo-root>`
- dsh: `0.2.0-rc.2`
- project key: `--<project-root-slug>--`
- normal session: `session-92a9ff44-7b78-4b1f-a278-259a6a5d4941`
- interrupted session: `session-b6f4f8fa-ea26-44e9-b7ab-ecb0f523ac44`
- resume cacheReadTokens: `6528`

| check | result |
| --- | --- |
| session_file_created | PASS |
| event_log_readable | PASS |
| normal_resume_lossless | PASS |
| kv_cache_reused | PASS |
| baseline_injected_once | PASS |
| interrupted_turn_visible | PASS |
| interrupted_step_visible | PASS |
| interrupted_tool_call_visible | PASS |
| interrupted_tool_result_closer | PASS |
| interrupted_turn_end_closer | PASS |
| open_turns_closed | PASS |
| open_steps_closed | PASS |
| baseline_still_once | PASS |
