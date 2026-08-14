# Changelog

All notable changes to Focus Agent are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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

[2.2.0]: https://github.com/GLASOO/Focus/releases/tag/v2.2.0
[2.1.0]: https://github.com/GLASOO/Focus/releases/tag/v2.1.0
[2.0.0]: https://github.com/GLASOO/Focus/releases/tag/v2.0.0
