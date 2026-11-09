# store.py — 状态读写

`load(path)`：文件不存在返回 `None`，否则解析 JSON。
`save(path, state)`：先写 `path.tmp` 再 `os.replace`，保证 `kill -9` 时不会读到半截 JSON。

只做 I/O，不含状态机逻辑；判断"该不该写"由 `loop.py` 和 `harness.py` 决定。
