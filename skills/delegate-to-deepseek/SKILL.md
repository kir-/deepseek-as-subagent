---
name: delegate-to-deepseek
description: Use DeepSeek as a bounded RL/ML research implementer. Claude remains planner and final judge; Codex performs adversarial review.
---

# DeepSeek Research Implementer

DeepSeek is a bounded implementation worker.

Claude remains responsible for:
- planning,
- mathematical specification,
- research judgment,
- final acceptance,
- deciding whether Codex review findings are valid.

Use DeepSeek only when the task has:
- a clear implementation spec,
- bounded file scope,
- explicit success checks,
- no need to invent the algorithm or research direction,
- no need to make final scientific claims.

Good DeepSeek tasks:
- implement a specified patch,
- add logging or diagnostics,
- add tests from a written invariant,
- update configs mechanically,
- write plotting/result aggregation scripts,
- perform batch refactors,
- scan files and summarize patterns.

Bad DeepSeek tasks:
- decide whether a research hypothesis is correct,
- invent estimator math,
- redesign the training algorithm,
- judge whether an experiment supports a paper claim,
- make broad architecture choices without a Claude-written spec.

After DeepSeek returns:
1. Claude must inspect the diff.
2. Claude should run Codex full-review.
3. If Codex fails any stage and code changes are made, restart review from software review.
