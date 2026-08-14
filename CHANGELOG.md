# Changelog

All notable changes to Focus Agent are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
- **Quality gates**: 102 unit tests in CI + `tests/live_eval_08b.py` live
  gate (tool calling / memory directives / long-horizon Zoom Out)
- Backlog consolidator (`focus/consolidate_backlog.py`) — 499 historical
  episodes → 303 live facts on the production graph
- Packaging: `pyproject.toml`; DeepSeek Harness plugin adapter draft

### Verified

- End-to-end on a local **0.8B** model (LM Studio, OpenAI-compatible API):
  the gate passed, including a long-horizon task where the model wrote its
  own artifact file to disk.

[2.0.0]: https://github.com/GLASOO/Focus/releases/tag/v2.0.0
