# DeepSeek Harness 插件适配方案（占位，待 dsh API 稳定）

状态：dsh 为开发者预览版（2026-08-13 开源，README 警告破坏性变更）。
本文件是适配设计占位，dsh v1.0 后实施。

## 架构
```
dsh (TypeScript) ──HTTP──> focus-memory-server (Python/FastAPI)
                              └── MemoryHarness (focus.memory)
```
dsh 的 storage/loop 插件位 → 桥接到本仓库记忆服务：
- `memory.write(fact)`  → POST /facts（走 add_fact 双时间轴）
- `memory.search(q)`    → POST /search（三路混合检索）
- `memory.dream()`      → POST /dream（模板提取+wiki+core）

## 触发条件
1. dsh 发布 v1.0 或插件 API 冻结公告
2. 本仓库记忆评测基准（tests/test_memory_eval.py）持续全绿
