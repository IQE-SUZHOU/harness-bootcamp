ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)
REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SPEC := $(ROOT)/docs/superpowers/specs/2026-10-30-multi-ai-agent-on-pipeline-for-validation-design_dsh.md
DSH  := $(ROOT)/dsh-superagent-prototype
BASE := 6337fc8
N    := grep -cE

.PHONY: init contract check verify verify-fake loop loop-real stop clear day5 day5-fake skills skills-test test

init: ## 自检：设计书 / dsh 基线 commit / pnpm
	@test -f $(SPEC) && echo "spec OK" || { echo "SPEC MISSING: $(SPEC)"; exit 1; }
	@git -C $(DSH) cat-file -e $(BASE)^{commit} && echo "dsh baseline OK ($(BASE))"
	@command -v pnpm >/dev/null && echo "pnpm OK" || echo "pnpm MISSING -> test 不可用"

contract: ## 架构契约门禁：设计书锚点逐项可数，且本仓库无密钥
	@echo "D 决策=12 实际=$$(sed -n '/^## 12/,$$p' $(SPEC) | $(N) '^\| D[0-9]+ \|')"
	@sed -n '/^## 12/,$$p' $(SPEC) | $(N) '^\| D[0-9]+ \|' | grep -qx 12
	@$(N) '^\| (Monitor|Reproduction) \| \*\*确定性' $(SPEC) | grep -qx 2
	@$(N) '^\| (Triage|Ticket|Reviewer|Reporting) \| \*\*[^|]*Session' $(SPEC) | grep -qx 4
	@sed -n '/^## 5\. 领域控制/,/^## 6\./p' $(SPEC) | $(N) '^\| (Trigger|Eval|Decision|Mandate|WorkItem|Assignment|EvidenceBundle|TicketDraft|Effect|Outbox|release_set) \|' | grep -qx 11
	@sed -n '/^## 11/,/^## 12/p' $(SPEC) | $(N) '^\| (安全基线|observe|内部授权闭环|真实只读|有限 auto) \|' | grep -qx 5
	@$(N) '不再使用 LangGraph/CrewAI' $(SPEC) | grep -qx 1
	@! grep -lqE 'sk-[A-Za-z0-9]{8,}' *.md && echo "no-secret OK"

check: contract ## 唯一能把功能项升为 passing 的入口

verify: ## Day3 门禁：静态 → 单测 → 故障注入 → 真实 LLM 断点续跑
	@python3 -m py_compile $(REPO)/src/*.py $(REPO)/tests/fake_llm.py $(REPO)/tests/fault_inject.py
	@python3 -m unittest discover -s $(REPO)/tests -p 'test_*.py'
	@python3 $(REPO)/tests/fault_inject.py
	@MODE=real bash $(REPO)/tests/e2e_resume.sh

verify-fake: ## 同一门禁的离线版（假 LLM，可反复回归）
	@python3 -m py_compile $(REPO)/src/*.py $(REPO)/tests/fake_llm.py $(REPO)/tests/fault_inject.py
	@python3 -m unittest discover -s $(REPO)/tests -p 'test_*.py'
	@python3 $(REPO)/tests/fault_inject.py
	@MODE=fake bash $(REPO)/tests/e2e_resume.sh

loop: ## Day4 循环演示：重试恢复 + 超限阻断（本地假模型，离线）
	@bash $(REPO)/tests/loop_demo.sh

loop-real: ## Day4 循环：真实任务 rocm_triage + 真实 LLM（同一任务重复 3 次）
	@bash $(REPO)/tests/loop_real.sh

day5: ## Day5 Demo：mini SWE agent 用真实 LLM 修测试，再由外部命令验收到 rc=0
	@python3 $(REPO)/swe/run.py --task $(REPO)/swe/tasks/bugfix_demo/task.json

day5-fake: ## Day5 离线版：脚本化假模型驱动同一套 agent / 环境 / 门禁
	@bash $(REPO)/swe/tests/day5_fake.sh

skills: ## 列出 vendor/amd-skills 快照里的技能
	@python3 $(REPO)/tools/skills.py list

skills-test: ## 技能 CLI 单测（list/search/prompt/install）
	@python3 -m unittest discover -s $(REPO)/tools/tests -p 'test_*.py'

stop: ## 停掉残留的 harness.py（kill -9 make 留下的孤儿）
	@pkill -f "[s]rc/harness.py" && echo "stopped leftover harness" || echo "no leftover harness"

clear: ## 清掉 loop-real 的续跑状态，下次从第 1 步重来
	@rm -f /tmp/harness-loop-real/state.json
	@echo "cleared /tmp/harness-loop-real/state.json"

test: ## dsh prototype 测试（需先在 dsh-superagent-prototype 跑 pnpm install）
	cd $(DSH) && pnpm check
