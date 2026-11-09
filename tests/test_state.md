# test_state.py — 门禁单测

`python3 -m unittest discover -s tests -p 'test_*.py'`

覆盖 `src/verify.py` 的每条不变量和退出码，全部离线、无模型调用：

- 完整 20 步、进行中、全新 0 步 → 必须通过
- `done` 与答案条数不符、步号重复、步号空缺、空答案 → 必须报对应错误码
- `ended` 未满步、`running` 已满步、非法状态值、缺字段、根不是对象 → 必须报错
- CLI 合法文件 rc=0、坏 JSON rc=2

新增不变量时，先在 `verify.py` 定义错误码，再在此补一条用例；门禁自身的回归靠这层单测，不靠人眼。
