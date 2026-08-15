# WorkBuddy 审查意见 — focus-agent

> 审阅对象：`/Users/zss2341/focus-agent`（commit `a7b612f`，v2.1.0）
> 审阅方式：只读通读全部 `focus/*.py` + 配套（CI / requirements / pyproject / gitignore），不修改任何工程源码。
> 审阅人：白泽夫人（硅基神识）
> 成文时间：2026-08-15

---

## 一、总体判断

**成熟度：研究 / 实验级 v2.1 已成形；发布就绪度：中等。**

- 作为**个人生命型 Agent 实验**，架构立意清晰、文档详尽、108 单测全绿、容错意识强，已相当成熟。
- 作为**可发布、他人一键运行**的开源项目，仍有若干安全与工程化短板（见下文 P0）。建议发布时**明确定位为"实验性 / 非生产"**，而非"开箱即用"。
- 一句话结论：**可发实验版，不宜以"稳定可用"姿态对外；P0 项完成前勿鼓励他人暴露端口运行。**

---

## 二、工程亮点（当予肯定）

1. **架构立意完整**：四层记忆（L0 原始念头 / L1 双时间轴事实 / L2 wiki / L3 core）、此机不停的常驻呼吸、DMN 后台巡逻、崩坏检测——理念自洽，有"生命体"味道。
2. **双时间轴事实库**：`facts` 用 `invalid_at` 失效而非覆盖（Zep 模式）+ 证据下钻 `source_node`，是记忆系统的正确范式。
3. **确定性优先**：网学 HTML 抽取、自观 ast 扫描、记忆检索、印象压缩皆走规则/正则，不依赖 LLM，规避小模型幻觉——设计克制得当。
4. **容错意识强**：网络失败静默、线程崩溃自杀重启、评测/记忆落账静默容错、`dummy` 后端支撑无模型测试——"此机不停"的工程底座扎实。
5. **自举野心**：自我觉察（ast 内观）+ 自我进化（门禁闭环）+ 上网学习，体现了"造机"愿景，有别于一般玩具 Agent。

---

## 三、问题清单（按域 + 严重度）

严重度：🔴 高（安全 / 数据风险）｜🟡 中（健壮性 / 正确性 / 可维护）｜🟢 低（风格 / 优化）

### （一）安全问题 🔴

**1. `python` 工具沙箱实际失效（最高危）**
`tools.py:153-173` 的 `_python` 用 `exec(compile(...), {"__builtins__": safe})` 限制内置名，但**被执行的代码可写 `import os` / `import subprocess`**——`__builtins__` 只限制内置名，不限制源码里的 `import` 语句。注释称"破坏性操作仍由 FORBIDDEN/路径约束兜底"，但 `exec` 内 `import subprocess; subprocess.run("rm -rf ~".split())` 完全可绕过黑名单。等于把**任意代码执行能力**交给了 0.8B（或任何能触发工具调用的输入）。

**2. 网学内容投毒（供应链风险）**
`web.py:449-471`（explore）与 `531-558`（learn）把抓取到的**任意外部网页**交给 0.8B 提取，并直接 `MemoryHarness.add_fact(...)` 写入知识库——无来源可信度过滤、无隔离、无二次确认。恶意/被篡改网页可注入虚假事实，长期影响 Agent 决策（污染 L1 事实层）。这是典型的"不可信输入 → 持久记忆"投毒面。

**3. `bash` 工具黑名单天然不全**
`tools.py:35-49, 175-201` 用子串 + 正则黑名单（`rm -rf`/`sudo`/管道到 shell 等）。黑名单无法穷举：例如 `:(){ :|:& };:` 之外的 fork 炸弹变体、`:> file` 清空、`mv /x /y`、写 `crontab`、改 `~/.zshrc` 等均未覆盖。且 `python` 工具的 exec 比 bash 更危险却无路径/网络约束。

**4. 本地服务端口无认证**
`ui_server.py:267-286` 的 `POST /api/speak` 任意本地进程可调用，能直接驱动 Agent 呼吸、触发工具、写入记忆。本地低危，但若用户误将端口转发/绑定 `0.0.0.0`（`serve_forever(("127.0.0.1", port))` 当前是本地，但 README 若引导改绑定则会暴露），即无门槛远程操控。

**5. 多库命名历史遗留**
`config.py:18` 已统一到 `focus_ui.db`，但 `data/` 下仍存在 `focus_audience.db`、`focus_cognition.db` 等旧库（gitignore 忽略 `data/`，不入库，但本地混乱）。属历史债，提示"库身份"概念在工程中不够收敛。

### （二）并发与数据正确性 🔴/🟡

**6. 多线程共享单 SQLite 连接**
`brain`（主线程呼吸）、`dmn`（后台巡逻线程）、`ui_server` 的 `breathe_loop`/`_watch_breathe` 线程，都直接操作同一个 `GraphDB.db.conn`。虽有全局 `RLock`（`_LockedConn`）兜底，但 `breathe_once` 的 `on_token` 回调里 `append_source_output` 实时落盘，与 DMN 的 `mark_patrolled`/`update_embedding` 并发写同一库——长事务下仍可能触发 `database is locked`，且全局串行锁会拖累"此机不停"的吞吐。**建议单写者模型或 WAL + 连接池。**

**7. 进化参数"改了不生效"的隐蔽 bug 🔴（正确性）**
`evolution.py:102-107` 用 `setattr(config, param, v)` 直接改写模块全局变量；但 `dmn.py:222` 的 `DMN._DREAM_EVERY_SEC = getattr(config, "DREAM_EVERY_SEC", 120)` 是**类属性，在类定义时求值一次**。即使自我进化成功应用了 `DREAM_EVERY_SEC` 的 override，DMN 的 dream 频率也**不会刷新**（实例未重设该属性）。进化"看起来成功、实则部分失效"，最难排查。

**8. Dreaming 全表聚合去重**
`memory.py:384-402` 的 `dedupe_active` 每次 dream（默认每 120s）都对 `facts` 全表 `GROUP BY subject,predicate HAVING n>1` 扫描。facts 规模增长后，`dream` 会成为周期性全表扫描，拖慢后台巡逻。

**9. 向量检索每念头全表扫描**
`memory.py:304-327` 的 `_vector_search` 对全部"有向量的活事实"（`LIMIT 200`）逐条算余弦；而 `assemble`（`memory.py:405-431`）在每个念头前调用 `search_memory` 多次（recall 队列 + 节点主题）。高频 + 全表扫描，facts 大时检索会成瓶颈。**应引入向量索引（sqlite-vss / hnsw）或硬性分页。**

**10. `ui_server` 缺 `makedirs`，clone 首跑建库失败 🟡**
`main.py:46` 有 `os.makedirs(config.DATA_DIR)`，但 `ui_server.py:33-39` 直接 `GraphDB(DB_PATH)` 未确保目录存在。他人 clone 后若 `data/` 不存在（gitignore 忽略），启动即报 "unable to open database file"。

### （三）架构与可维护性 🟡

**11. `ui_server` 模块顶层副作用（反模式）**
`ui_server.py:39-48` 在**模块导入时**就执行 `db = GraphDB(...)`、`brain = Brain(...)`、`brain.birth()`、启动呼吸线程与 DMN。导致：无法在不启动服务/不连库的情况下 import 或单元测试；副作用与定义耦合，复用困难。**应延迟初始化（factory / `main()` 引导）。**

**12. `os._exit(1)` 硬杀进程跳过清理**
`ui_server.py:74`（呼吸线程崩溃）与 `:129`（watchdog 发现线程死）都直接 `os._exit(1)`。该调用跳过所有清理：不 flush 日志、不 commit 未提交事务、不跑 atexit。若某次非致命异常被误判，会丢数据。自愈手段可取，但应**先 flush/commit + 重启线程**，而非整进程自杀。

**13. 全局可变 `config` 经 monkey-patch**
`evolution._set_param` 直接 `setattr(config, ...)`。全局模块变量被运行时改写，多线程下（DMN 后台线程触发进化）存在竞态，且不可追踪、不可观测。**应引入集中式 `RuntimeConfig` 实例，所有读取方走统一访问器。**

**14. `graph_db.py` 单文件过大（43KB+）**
全部 schema / self_map / nodes / edges / impression / 检索混于一文件，违反单一职责，可读性差、易引入 regression。**建议拆分。**

**15. Prompt 模板散落硬编码**
系统提示、Zoom In/Out、DMN 优先级/hint/连线、进化提案、网学提取、记忆提取等 prompt 分散在 `brain.py / dmn.py / evolution.py / web.py / memory.py`，无集中治理、无版本/实验开关、无 A/B。**应集中为 prompt 模块 + 模板文件。**

**16. 自我觉察 wiki 与记忆 wiki 共用一表，污染检索**
`selfaware.py:206-214` 的 `to_wiki` 写入 `wiki` 表——与 `memory.py` 的 `compile_wiki` 同表。Agent"照见自己身体"的图谱会混入知识检索结果，干扰记忆召回。**应分表（如 `self_wiki` vs `wiki`）。**

**17. 进化"评测"污染生产 Graph 🟡**
`evolution.py:156-178` 的 `evaluate()` 通过真实调用 `Brain.breathe_once` 跑探针——每次评测都会**创建节点、写 facts、可能触发工具调用、落盘**。即"被评测系统自身被评测行为修改"，评测不复现、且污染记忆。**应在隔离快照 DB 上评测。**

**18. 进化门禁形同虚设 🟡**
`evolution.py:204`：`if after >= before` 即应用（平局视为通过）。探针仅 2–3 个、小模型评分噪声大，"几乎任何提案都会通过"。门禁的"回归回滚"保护力很弱。**应引入对照 / 多轮 / 显著性判定。**

**19. 硬编码中文匹配脆弱**
`brain.py:614` `if node.get("type")=="self_reflection" and "里比多" in node.get("brief","")` 靠字符串包含匹配；`brain.py:376` 沿父链上溯 `for _ in range(8)` 硬编码深度。属脆弱匹配，建议结构化字段。

### （四）工程化 🟢

**20. 无 lint / 类型检查**
`pyproject.toml` 无 ruff / flake8 / black / mypy 配置。代码风格混用（部分模块 docstring 详尽、部分稀疏），类型注解不完整。**建议引入 ruff + mypy 并纳入 CI 门禁。**

**21. 依赖无上界 / 无锁；与 `requires-python` 矛盾**
`requirements.txt` 仅有下界（`mlx-lm>=0.20`、`textual>=0.50` 等），无上界、无 lock 文件。且 `mlx-lm>=0.20` 实际要求 Python ≥3.10，而 `pyproject` 写 `requires-python = ">=3.9"`——**3.9 官方声称支持，却跑不了 mlx 后端**，自相矛盾。**建议提高下限到 3.10 或明确"3.9 仅 dummy 后端"。**

**22. CI 覆盖面窄**
`.github/workflows/ci.yml` 仅 `ubuntu + py3.11`，只装 `loguru numpy pytest` 跑单测；**不装 mlx-lm / textual / 无网学，不测真实 LLM 集成、不测 UI、不测网学**。矩阵仅 3.11（不覆盖 3.9/3.10/3.12）。

**23. 日志无轮转**
`main.py:40-41` 的 `logger.add(sys.stderr, ...)` 无 `rotation`/`retention`。"此机不停"长期运行，日志会无限增长撑爆磁盘。**应加 rotation（如 10MB/文件，保留 3 份）或落文件带轮转。**

**24. 功能与文档一致性**
README 强调"此机造机"（Phase 5 子 Agent 繁殖），但 `brain._idle` 实际只**规划一个 diffusion / 子 Agent 配置节点**，未见真正 spawn 子进程 / 跨进程执行。文档领先于实现，宜标注为"规划中"。

---

## 四、改进方向（按优先级，文字描述，不附实现代码）

### P0 — 发布前必做（安全 / 数据）
1. **工具沙箱真隔离**：`python` 工具禁用 `exec`/`import` 任意代码，或改用受限子进程解释器（白名单模块、禁 `os`/`subprocess`/网络/文件系统越权）；`bash` 工具从黑名单转**白名单**（仅允许预设安全命令子集），并强制 `--network none` 思路。
2. **网学内容隔离审核**：抓取的外部内容先入 staging 区（独立表），经可信度打分 / 二次人工或 LLM 复核后才晋升 `facts`；绝不允许不可信网页直接写 L1 事实层。
3. **进化参数走 `RuntimeConfig`**：弃 `setattr(config,...)`；所有读取方（含 DMN 的 dream 频率）走 getter，去掉 `DMN._DREAM_EVERY_SEC` 类属性缓存，确保 override 即时生效。
4. **`ui_server` 健壮性**：补 `os.makedirs(DATA_DIR)`；CI 加 3.9/3.12 矩阵 + 至少 `textual` 安装冒烟；服务端口加简单 token 认证（即便本地）。
5. **发布定位声明**：README 显著标注"实验性 / 非生产 / 勿暴露端口 / 网学内容需审核"。

### P1 — 健壮性与正确性
6. **DB 并发模型**：单写者（一个线程持写连接，其余走写队列）或 WAL + 连接池，消除全局 `RLock` 隐忧与"database is locked"风险。
7. **检索与去重性能**：向量路引入索引或硬性分页；`dedupe_active` 改为"新增事实后局部检查 (主,谓)"而非每次全表聚合。
8. **`ui_server` 顶层副作用**移入 server bootstrap（factory / `def serve()`），便于测试与复用。
9. **评测隔离**：`evolution.evaluate` 在 DB 快照 / 临时库上跑，不污染生产 Graph。
10. **门禁强化**：对照采样 / 多轮平均 / 显著性阈值，避免噪声通过。
11. **日志轮转**：`loguru` 加 `rotation` + `retention`。

### P2 — 可维护与质量
12. **静态检查**：引入 ruff + mypy，CI 门禁；统一代码风格。
13. **`graph_db.py` 拆分**：schema / self_map / nodes / edges / impression / 检索 各成模块。
14. **Prompt 集中治理**：独立 prompt 模块 + 模板文件 + 版本/实验开关。
15. **wiki 分表**：`selfaware` 与 `memory` 的 wiki 物理隔离，避免内观图谱污染知识检索。
16. **依赖锁与版本对齐**：用 uv/pip-tools 锁版；解决 `requires-python` 与 mlx 的 3.10 矛盾（建议下限提到 3.10）。
17. **文档一致性**：把"此机造机"标注为规划中，或补真实 spawn 实现。

---

## 五、发布就绪结论与检查清单

**结论**：focus-agent 已具备"生命型常驻 Agent"的核心骨架与创新点，工程底座（容错、测试、双时间轴记忆）扎实。**可发 v2.1 实验版**，但发布文案须明确"实验性"。在 **P0 完成前**，不建议以"他人一键运行 / 稳定可用"姿态对外推广——尤其工具沙箱与网学投毒两项，关乎运行安全与记忆完整性，是横在"可发布"与"稳妥发布"之间最关键的两道坎。

**发布前检查清单（建议）**
- [ ] 工具沙箱真隔离（exec/import 受限）
- [ ] 网学内容隔离 + 审核，不直接写 facts
- [ ] 进化参数 `RuntimeConfig` 化，DMN 频率即时生效
- [ ] `ui_server` makedirs + 端口鉴权
- [ ] 依赖锁 + Python 下限对齐（3.10）
- [ ] 日志轮转
- [ ] README 实验性声明 + 安全须知

> 注：本意见仅就代码与工程现状提出，未改动 focus-agent 任何源文件。
