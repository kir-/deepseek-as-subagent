---
description: Use DeepSeek as a bounded research implementer with an explicit task contract.
---

# /ds-impl

Use DeepSeek as a bounded research implementer.

Before calling DeepSeek:
1. Write a concise implementation contract.
2. Include mode, allowed_files, forbidden_files, must_not_change, and success_checks.
3. Do not ask DeepSeek to invent research direction or final mathematical judgment.

Call delegate_to_deepseek with:
- task
- context
- contract

User request:

```
$ARGUMENTS
```

After DeepSeek returns:
1. Inspect changed files and diff stat.
2. Run Codex full-review.
3. If Codex fails any stage and code changes are made, restart from software review.
4. Claude makes the final decision.
