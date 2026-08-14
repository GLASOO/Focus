# Contributing to Focus Agent

此机不停 — and neither is the bar for merging.

## Ground rules (the genes apply to code too)

1. **Never stop the machine.** Any change that can halt the breathing loop in
   production is a defect, not a feature. Exception handling in the loop must
   degrade, never propagate.
2. **Determinism where the model is weak.** Small models drift; the harness
   must not. Memory writes, retrieval, and context assembly are pure
   engineering — no LLM call is allowed on the retrieval path.
3. **The gate is the gate.** `tests/live_eval_08b.py` passing is a release
   criterion, not a nice-to-have. If you touch prompts, routing, tools or
   memory parsing, run it against a live small model before opening a PR.
4. **Evidence over summary.** Thoughts land raw; facts carry `source_node`.
   Keep it that way — every derived artifact must be drillable to its evidence.

## Workflow

```bash
pip install loguru numpy pytest
pytest tests/ -q                    # 102 unit tests must stay green
python tests/live_eval_08b.py       # needs an OpenAI-compatible small model
```

- Branch from `main`; keep commits atomic and honest (say what broke and why).
- Prompt changes must include the observed failure they fix — our prompt
  comments are a fossil record of 0.8B misbehavior. Preserve it.
- No new hard dependencies without a gene-level reason.

## What we will not merge

- Anything that batches breaths, dilutes focus, or silences the watchdogs.
- Retrieval paths that call an LLM.
- Personal identifiers, absolute home paths, or secrets (the release was
  scrubbed once; keep it scrubbed).

## Ideas worth bringing

- Raising the 0.8B long-horizon success rate (~⅔ per gate run) — scaffolding,
  routing, or evaluation work.
- The DeepSeek Harness plugin adapter (`packaging/DSH-PLUGIN.md`).
- New retrieval routes that stay zero-LLM and sub-second.
