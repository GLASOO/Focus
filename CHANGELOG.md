# Changelog

All notable changes to Focus Agent are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.4.0] — 2026-08-15

### Added — SoulForge: every thought wears its own soul

The system prompt is fixed like a constitution (the Five Genes); but every
single thought now gets its own prompt — a temporary soul forged
deterministically (zero LLM — no hallucination allowed in the soul):

- 临时身份 (temp identity): worn by node type/role/brief markers
  (对话者 / 执行者 / 边界守护者 / 领土开拓者 / 看整体者 …)
- 临时自我 (temp self): one line of living state (libido, focus count,
  thoughts landed so far)
- 临时目标 (temp goal): this breath's deliverable + lineage back to the
  root task (drift-proof) + delivery form hints (write-to-file ⇒ tools)
- 临时念头 (temp seed): hint + sibling context — where am I, who is
  beside me

Soul is injected into all four prompt paths (conversation / Zoom In /
generic task / Zoom Out), hard-capped at 350 chars. 10 deterministic tests.
Live acceptance on 0.8B: asked about its own temporary identity and goal,
the agent answered both correctly from its injected soul.

## [2.3.0] — 2026-08-15

### Added — Self-awareness v1 (the foundation of self-evolution)

Premise (from the design book): self-awareness is the foundation of
self-evolution — the agent must hold all knowledge of itself inside its own
memory, and be able to understand its own code.

- `focus/selfaware.py`: deterministic self-introspection (zero LLM — no
  hallucination allowed in self-perception).
  - `scan()`: AST-parses its entire body (`focus/*.py`) into
    `self_knowledge` (modules / classes / methods / duties from docstrings);
    file-hash change detection — it notices when its body changes, including
    edits made by collaborating construction agents.
  - `selfmap` / `selfread` tools registered for the brain: the agent can now
    actively look at its own structure and read its own code (restricted to
    `focus/*.py`).
  - `to_wiki()`: the body map is compiled into the wiki page 《我的身体》,
    searchable like any other memory.
  - Dreaming scans the body every cycle; evolution proposals are now
    grounded in a self-summary — proposals must stand on self-awareness.
- First real introspection (production graph): 19 organs indexed, 305
  self-knowledge entries; `understand("breathe_once")` answers correctly.
- 8 deterministic tests.

### Hardened during live introspection acceptance (same day)

- Tool second-turn: after a tool call, real results are fed back for one
  more generation round — 0.8B otherwise ignores results and hallucinates
  (observed: invented human anatomy instead of reading selfmap output).
- Tool-call parser tolerates `[tool=name]` bracket variants.
- Argument guardrail: >300-char args are refused with a correct example.
- Conversation prompts scrub all `<tool=…>` tags (they can trigger the stop
  sequence prematurely); self-awareness summary is injected into every
  conversation, so simple self-questions need no tool call at all.

## [2.2.0] — 2026-08-15

### Added — Self-evolution v1 (the stated goal, first gated step)

- `focus/evolution.py`: **proposal → gate → apply/rollback** loop.
  - Evolution domain is a strict parameter whitelist with hard bounds
    (0.8B is never allowed to touch code).
  - Proposal protocol `【调】param|value|reason` with tolerant parsing
    (full-width pipes, missing separators — observed 0.8B behaviors).
  - Gate: fixed probe suite scored before/after; regression ⇒ automatic
    rollback + lesson recorded (fed back into the next solicitation).
  - Overrides persist in `proposals` table and replay on startup.
- Wired into Dreaming at low frequency (one cycle / 6 h, silent-safe).
- CLI: `python -m focus.evolution cycle|status`.
- 10 deterministic unit tests.

### Verified — first real evolution cycle (0.8B, production graph)

The agent proposed `IDLE_INTROSPECT_MAX_RATIO → 0.85`; the gate measured a
regression (3.0 → 1.5); the system rolled back and logged the lesson.
A correct rejection is a working loop.

## [2.1.0] — 2026-08-15

### Added

- **Conversation gate (class D)**: `tests/live_chat_eval.py` — deterministic
  heuristics (substance, no meta-roleplay, no prompt leakage, follow-up
  recall). Baseline was 0/5; after Pi-style prompt slimming + recent-dialog
  injection + routing fix: 3 rounds 3/5 · 5/5 · 4/5, recall 3/3.
- **Web curiosity module** (`focus/web.py`): zero-dependency web learning
  pipeline, `FOCUS_WEB=0` to disable. Contributed by a collaborating
  construction agent (文昌夫人) — one of several agents working on this repo.
- Tool sandbox hardening (regex FORBIDDEN_PATTERNS: pipe-to-shell, eval/exec,
  block devices) — same collaborator.
- Note: true self-evolution of Focus Agent itself remains the project goal;
  see the evolution module for the first gated step.

### Changed

- Conversation prompt slimmed from ~40 instruction lines to identity +
  recent dialog + memory + 4 rules (small models drown in instruction piles).
- Idle governance may now produce web-learning nodes instead of territory
  growth (deterministic fallback preserved).
- Test suite 102 → 108.

## [2.0.0] — 2026-08-14

First public release. The machine breathes.

### Added

- **Memory v2**: four-layer memory (episodes / bi-temporal facts / wiki /
  core) with evidence drill-down to source thoughts
- **Memory directives** `【记】/【忘】/【忆】` — deterministic tool calling for
  small models, with tolerant parsing (missing headers, full-width pipes)
- **Zero-LLM hybrid retrieval**: FTS5/BM25 + LIKE (CJK) + cosine vectors +
  graph traversal, time decay, per-subject dedup, hard context budget
- **Dreaming**: background consolidation pipeline (template extraction →
  wiki assembly → core compaction → contradiction self-healing)
- **Event sourcing** observability (`events` table, trajectory replay)
- **Tool layer** `ls/cat/pwd/python/bash` with directory allowlist and
  forbidden-command list; sandboxed python with whitelisted builtins
- **Idle governance**: spinning detection, territory-growth nodes, libido
  seed re-focus enforcement
- **Resilience**: OS-level (launchd) + thread-level watchdogs; crash ⇒
  resurrect with memory intact; serialized sqlite connection proxy
- **Quality gates**: 108 unit tests in CI + `tests/live_eval_08b.py` live
  gate (tool calling / memory directives / long-horizon Zoom Out)
- Backlog consolidator (`focus/consolidate_backlog.py`) — 499 historical
  episodes → 303 live facts on the production graph
- Packaging: `pyproject.toml`; DeepSeek Harness plugin adapter draft

### Verified

- End-to-end on a local **0.8B** model (LM Studio, OpenAI-compatible API):
  the gate passed, including a long-horizon task where the model wrote its
  own artifact file to disk.

[2.4.0]: https://github.com/GLASOO/Focus/releases/tag/v2.4.0
[2.3.0]: https://github.com/GLASOO/Focus/releases/tag/v2.3.0
[2.2.0]: https://github.com/GLASOO/Focus/releases/tag/v2.2.0
[2.1.0]: https://github.com/GLASOO/Focus/releases/tag/v2.1.0
[2.0.0]: https://github.com/GLASOO/Focus/releases/tag/v2.0.0
