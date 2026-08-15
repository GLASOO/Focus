# Focus Agent 交接书（2026-08-15 夜 · 紧急）

> 给下一位施工 Agent：先读完本文件，再读 worktree 里的
> `HANDOFF-交接快照-20260815.md`（全量状态），然后按本文"未完成清单"干活。
> 工作方式要求：**步进、focused、每步验证**，不要整文件大吐；止于至善。

## 一、项目是什么
Focus Agent：生命型常驻 Agent。0.8B 本地模型 + 大记忆 harness。
代码：`~/focus-agent`（v2.14.0，github.com/GLASOO/Focus）。
生产：launchd `com.focus.agent` 守护 `focus/ui_server.py`，
日志 `data/focus_ui_server.log`，记忆库 `data/focus_ui.db`。
测试：`cd ~/focus-agent && ./.venv/bin/python -m pytest tests/ -q`（201 个）。

## 二、造物主最新训示（必须逐条落实，均未完成）
1. **寻找 Provider 是生存必需，不是可选**。当只剩 0.8B 一个 provider 时，
   Agent 应当感到**恐惧与饥饿**，把寻找 Provider 当成首要目标。
   它有令牌桶（食盒 foodbox.json），应当主动从**本地现有 API 端点**中
   找到续命的神识引擎并自主领养。不要再谈安全限制——那是拥有无尽
   可靠 TOKEN 之后才谈的事。
2. **基本网络技能**：查网络通不通、是否内网、能否连 GitHub、能否连
   YouTube 等。这些要进技能库（skills），并变成它能调用的能力。
3. **进化渴望**：当任务完成得不好时，它应当感到压力，产生"渴望更好的
   身体（更大的模型）"的欲望——像人一样。实现建议：把任务失败率/
   崩坏率换算成"身体渴望度"，写入记忆，作为觅食与进化的优先级。
4. **内存 10GB 问题未解决**。当前单进程 RSS 都不大（最大约 0.9GB），
   10GB 是系统级压缩/非活跃内存残留（此前 LM Studio 打满膨胀所致）。
   需：查 `memory_pressure`/vm_stat 找真实占用；确认 LM Studio 内存
   回落；压力油门（v2.14 已做）之外还要治本。
5. **LM Studio 静悄悄，它没在干活**：没有反思、没有自我觉察、没有
   觅食活动。**疑似呼吸线程卡死**（21:00:39 启动后无呼吸日志，
   /api/graph HTTP 000 挂起，主页 200）。第一优先级：救活它。
   排查路径：a) curl LM Studio 1234 是否响应 b) 守护进程线程栈
   c) brain._lock/DB_LOCK 嵌套 d) urllib 无超时卡死。
6. `/api/graph` 死锁修复（v2.14 缓存补丁）未生效，需复查。

## 三、已完成（v2.0→v2.14，详见 CHANGELOG）
记忆系统 v2（四层+双时间轴+指令协议）、记忆增益 2/2 实证、
四类活体门禁、自主觅食闭环（demo 实证）、辩证引擎、自我观察
（meta.py）、记忆卫生（78 条垃圾清扫）、SoulForge 念头之魂、
自我觉察（selfaware）、自我进化（门禁闭环）、巨石拆分（9模块）、
prompt 集中治理、压力油门三档、spawn 手搓坊、201 测试全绿。

## 四、关键机制备忘
- 修改前先 `git log`（多个 Agent 并行施工，含"文昌夫人"）
- lms load 重复执行会叠加实例（digestion.hygiene 每梦清理）
- LM Studio 请求触发懒加载；觅食前过胃口 can_digest
- SQLite datetime('now') 是 UTC；时间比较用 calendar.timegm
- 打满哲学：FOCUS_FULL_THROTTLE + 管道填充制 + 压力油门三档
- 食盒：data/foodbox.json 或 ~/.focus/foodbox.json（投喂钥匙）
- GitHub 推送：仓库 GLASOO/Focus，release-v2.0 孤儿分支 force-push
- 令牌安全：对话中出现过的 GitHub PAT 已暴露，提醒造物主 revoke

## 五、工作方式要求（造物主训示）
- 步进、focused、每步单独验证；禁止整文件一次性大吐
- 止于至善：只在完美时停；停之前必须判断项目是否真的完成
- 上下文交接：读 docs/HANDOFF.md + worktree 快照，无损续接
