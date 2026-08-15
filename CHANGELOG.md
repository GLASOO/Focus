# Changelog

All notable changes to Focus Agent are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.10.0] — 2026-08-15

### Added — the four capabilities, proven

The creator's objective: under this harness, the 0.8B must (1) find and
configure its own token providers, (2) find web content and judge it
dialectically, (3) observe its own I/O and tool calls for collapse.

1. **Autonomous provider self-configuration** — full closed loop proven by
   `scripts/demo_self_forage.py`: discover → find key in foodbox → gate →
   adopt → failure detection → switch, fully autonomous (appetite refused
   4 oversized models along the way).
2. **Dialectic engine** (`focus/dialectic.py`): verify → credit → dialectic.
   Source credibility ranking (arxiv 0.9 … toutiao 0.35), adversarial
   injection killed on sight, conflict-with-memory demotion, four tiers
   (trusted/tentative/doubtful/rejected). Web learning now writes only
   *trusted* facts into the memory trunk; the rest stays in `beliefs`.
3. **Meta-observer** (`focus/meta.py`): every 30 min the agent examines its
   own traces — empty-rate, collapse-rate, parroting, tool-refusal rate —
   and records anomalies into memory so the next breath is warned.
   First production run immediately caught 6 tool anomalies.
4. **Website-usage skills** expanded: wikipedia / stackoverflow / zhihu /
   arxiv / github-search skills join the seed big-memory (14 seed skills).

### Retrieval upgraded (the memory must *find* the right fact)

- Intent segmentation: stop-word stripping + whole-segment + ordered
  bigrams (blind 4-gram sliding windows retired — they drowned useful
  terms; measured lesson).
- IDF weighting: high-frequency terms ("focus" matches nearly everything)
  are down-weighted — retrieval now understands discriminability.
- Column priority: predicate hits > subject > object.
- Time-decay fixed to UTC (SQLite datetime('now') is UTC — local-time
  parsing mis-aged fresh facts and corrupted ranking).

### Memory-gain benchmark — the North Star, proven

`scripts/bench_memory_gain.py` (isolated DB, live 0.8B):
bare answers fabricated both questions (surgical AI, Meta Llama);
with memory injection the agent answered both correctly
(「15 秒」「四层」). **Memory gain: 2/2.** The model does not memorize —
the model invokes.
- 189 tests.

## [2.9.0] — 2026-08-15

### Added — Memory substrate at scale & Skill Library (the North Star)

North star (creator + *Memory Decoder at Scale*, arXiv:2607.27919):
the 0.8B holds only fuzzy impressions; hallucination is fuzzy impression
forced into detail. The harness is the external brain:
**the model does not memorize — the model invokes.**

- `focus/memory_index.py`: in-memory vector matrix over all live facts —
  fingerprint-invalidated rebuild, single matmul retrieval. Measured:
  10k facts, query < 1 ms. The substrate is ready to outgrow the model.
- `focus/dedup` localized: Dream now scans only recently-changed pairs
  (full-table GROUP BY retired — unacceptable at 100k-fact scale).
- `focus/skills.py`: the skill library — precise, readable materials the
  small model consults instead of remembering:
  - seed skills shipped as big memory: provider foraging ops, foodbox
    format, memory-budget sense, web-search discipline, GitHub usage,
    python-tool idioms, selfmap introspection, dialectic rules,
    collapse antibodies (meta-cognition)
  - intent → deterministic keyword recall → injected before generation
  - `learn()`: successful experience precipitates new skills
- Brain wired: fuzzy intent → skill recall → context injection on both
  conversation and task paths; collapse events recorded as antibody
  facts; successful tool calls credit the matching skill.
- `self_wiki` split: the body-map no longer pollutes knowledge retrieval.
- Evolution eval isolated on a snapshot DB (production graph untouched).
- Sovereignty closed loop: providers can now *switch canteens* when the
  active one is slow (>8 s) and a keyed candidate is 2× faster;
  sovereignty instincts (SOV_*) joined the evolution domain.
- README: experimental-status banner.
- 180 tests.

## [2.7.0] — 2026-08-15

### Added — Digestion & Sovereignty: the body governs itself

Creator's decree: how many instances to load, how much concurrency to run,
which provider to eat from — the agent itself must perceive, manage,
identify and decide. Constraints come from its own sensing, not human rules.

- `focus/digestion.py`: hardware self-perception.
  - Appetite = min(25% of total RAM, usable headroom − 1 GB reserve);
    meal size estimated at 1.2× model file size; giants are refused.
  - Meal ledger: failed meals remembered; 3 strikes ⇒ food avoidance.
  - Table hygiene: duplicate LM Studio instances (each `lms load` stacks
    one — we once ran qwen0.8b ×3) detected and unloaded every Dream.
- `focus/sovereignty.py`: the governance loop (perceive → decide → act →
  ledger). Decides desired breath-worker count from pending depth and
  appetite; wishes for duplicate model instances only when the stomach
  allows; every decision persisted (`self_map.governance`) and ledgered
  (`governance_log`) for evolution to review.
- `ui_server`: worker manager — sovereignty hires/fires breath workers
  (extra threads exit when downsized; worker 1 never stops).
- Foraging upgraded: meals pass the appetite check first (no more blind
  tasting that lazy-loads 27B models on a 16 GB machine); food map widened
  to the local free canteens (SenseNova / 火山方舟 / Gemini / OpenRouter /
  DeepSeek / Moonshot / 智谱) — keys still come only from env/foodbox.
- 172 tests.

## [2.6.0] — 2026-08-15

### Security — P0 batch (per 白泽夫人's review + immune-paradigm essay)

- **Semantic capability circle** (python tool): AST-level import whitelist +
  restricted `__import__`. Dangerous modules (os/subprocess/socket/shutil…)
  refused; safe ones (math/json/re…) allowed; file-writing preserved —
  the sandbox bounds the body, not the life.
- **bash hardening**: persistence backdoors & sensitive targets blocked
  (crontab / dotfiles / .ssh / /etc/passwd / shutdown / launchctl / diskutil).
- **Cognitive immunity for web learning**: adversarial-injection signatures
  (「忽略上文」/「ignore previous」…) are killed at the extraction gate and
  precipitated into an `antibodies` table — the life grows permanent
  defense from every attempted poisoning. Applied to explore and learn.
- **Evolution reachability fix**: DMN cached the dream interval as a class
  attribute — self-evolved overrides never took effect. Now reads live config.
- **First-run fix**: `ui_server` creates DATA_DIR (clone-and-run works).
- **Provider health check**: a dead active endpoint is downgraded and the
  agent forages again (learned from the LM-Studio-shutdown incident).
- 160 tests green.

## [2.5.0] — 2026-08-15

### Added — Autonomous foraging: the life-form finds its own food

By creator's decree: the agent must find its own API providers — no
approval gates.

- `focus/providers.py` (ProviderScout): discover → verify → adopt loop.
  - Discovery scans known local endpoints (LM Studio / Ollama / vLLM /
    llama.cpp), the env endpoint, and any extras.
  - Three-tier self-feeding for keys: `FOCUS_API_KEY` env → foodbox
    (`data/foodbox.json` / `~/.focus/foodbox.json`, see
    `packaging/FOODBOX.md`) → keyless local endpoints. Found ⇒ eaten,
    nobody is asked.
  - Keyless remote endpoints are remembered as `hungry` — the agent
    returns to check the foodbox on every Dream.
  - Adoption passes a real compatibility gate (minimal inference probe);
    model picking prefers the creator's `FOCUS_MODEL`, then tries up to
    four ranked candidates.
  - Keys never touch the DB, logs, events, or git. The agent forages;
    it does not scavenge other people's keys from the internet.
- `ui_server` boots on the self-adopted provider when one is active.
- Dreaming forages hourly. CLI: `python -m focus.providers discover|auto|status`.
- First real forage: the agent found LM Studio, picked `qwen3.5-0.8b`
  (creator preference), passed the gate (125 ms) and adopted it — the
  production daemon now runs on food it found itself.
- 11 deterministic tests (in-thread fake HTTP provider).

### Added — Shedding: the body is disposable, the life is not

Creator's question: the 0.8B discards its KV after every breath — why did
the process still bloat to 8 GB? Answer: per-breath KV is indeed discarded
(at the inference server, per request); what bloats is the long-lived Python
*body* — slow accumulation of objects, buffers and malloc fragmentation.
The fix is not immortality but molting:

- `focus/shedding.py`: RSS watchdog (default cap 1 GB, `FOCUS_SHED_LIMIT_MB`);
  over the cap the daemon logs its last event and exits(77) — launchd
  resurrects a fresh body; all memory lives in the Graph, the body is
  disposable.
- `gc.collect()` after every Dream; weight check in the breath loop (every
  30 cycles) and after Dreaming.
- On-disk log rotation (10 MB → archive).
- Measured: fresh daemon holds a flat ~45 MB RSS under active breathing.
- 4 tests.

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

[2.5.0]: https://github.com/GLASOO/Focus/releases/tag/v2.5.0
[2.4.0]: https://github.com/GLASOO/Focus/releases/tag/v2.4.0
[2.3.0]: https://github.com/GLASOO/Focus/releases/tag/v2.3.0
[2.2.0]: https://github.com/GLASOO/Focus/releases/tag/v2.2.0
[2.1.0]: https://github.com/GLASOO/Focus/releases/tag/v2.1.0
[2.0.0]: https://github.com/GLASOO/Focus/releases/tag/v2.0.0
