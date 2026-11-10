PY   := python3
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PYTHONPATH := $(ROOT)/src

.PHONY: init contract test check quiz audit ablate restore start finish resume verify loop teachback clean

init: ## 环境自检：必需工具缺失即失败，不装不做兜底
	@bash $(ROOT)/init.sh

contract: ## 工件契约门禁：结构、路由链接、状态机、无密钥
	@$(PY) $(ROOT)/scripts/check_contract.py

test: ## 单元测试
	@$(PY) -m pytest -q -x $(ROOT)/tests

check: contract test ## 唯一能把功能项升为 passing 的入口

quiz: ## 全新会话测试：只看仓库能否回答五个基本问题
	@$(PY) $(ROOT)/scripts/onboarding_quiz.py

audit: ## 五元组打分，并验证门禁本身可咬人
	@$(PY) $(ROOT)/scripts/audit_score.py

ablate: ## 消融实验：逐个移除指令/反馈/状态并强制恢复
	@$(PY) $(ROOT)/scripts/ablate.py all

restore: ## 恢复被消融移走的工件
	@$(PY) $(ROOT)/scripts/ablate.py --restore

start: ## 上班
	@$(PY) $(ROOT)/scripts/session.py start

finish: ## 下班
	@$(PY) $(ROOT)/scripts/session.py finish

resume: ## D2 状态持久化演示：杀进程后从检查点续跑（PASS 才 rc=0）
	@$(PY) $(ROOT)/scripts/state_demo.py demo

verify: ## D3 验证演示：半截产物/静默篡改/空口胜利全部被 checker 拒收（PASS 才 rc=0）
	@$(PY) $(ROOT)/scripts/verify_demo.py demo

loop: ## D4 图演示：fan-out 并行、重试预算、失败传播、独立支不误伤（PASS 才 rc=0）
	@$(PY) $(ROOT)/scripts/graph_demo.py demo

teachback: ## D5 整体验收：六 gate 全绿 + 实时工件盘点 + 遗留链 + 业务 Top3（PASS 才 rc=0）
	@$(PY) $(ROOT)/scripts/teachback.py

clean: ## 清缓存与实验残留（恢复后才允许清）
	@$(PY) $(ROOT)/scripts/ablate.py --restore
	@rm -rf $(ROOT)/.pytest_cache $(ROOT)/__pycache__ $(ROOT)/.harness_cache
	@find $(ROOT) -name __pycache__ -type d -exec rm -rf {} +
