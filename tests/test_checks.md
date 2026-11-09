# test_checks.py — 单步校验器单测

`python3 -m unittest discover -s tests -p 'test_checks.py'`

- `triage`：合法 JSON 通过；带 ```json 围栏也能提取；verdict 与事实不符、坏 JSON、空 evidence、id 不符、reason 过短全部被拒
- `report`：含步号和结论通过；缺步号被拒

纯函数测试，不联网。
