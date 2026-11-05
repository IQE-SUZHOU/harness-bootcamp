PY   := python3
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PYTHONPATH := $(ROOT)/src

.PHONY: init contract test check quiz audit ablate restore start finish clean

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

clean: ## 清缓存与实验残留（恢复后才允许清）
	@$(PY) $(ROOT)/scripts/ablate.py --restore
	@rm -rf $(ROOT)/.pytest_cache $(ROOT)/__pycache__ $(ROOT)/.harness_cache
	@find $(ROOT) -name __pycache__ -type d -exec rm -rf {} +
