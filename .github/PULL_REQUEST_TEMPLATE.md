## What changed and why

<!-- say what broke and why; prompt changes must cite the observed 0.8B
     misbehavior they fix -->

## Checklist

- [ ] `pytest tests/ -q` — 108 tests green
- [ ] `python tests/live_eval_08b.py` — gate run against a live small model
      (or explanation why not applicable)
- [ ] no new hard dependency without a gene-level reason
- [ ] no personal identifiers, absolute home paths, or secrets
- [ ] retrieval paths remain LLM-free
- [ ] the breathing loop cannot be halted by this change
