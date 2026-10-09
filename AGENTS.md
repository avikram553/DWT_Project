# DWT Project — Codex Guidelines

Derived from Karpathy's observations on LLM coding pitfalls.

## 1. Think Before Coding

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

## 3. Surgical Changes

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If unrelated dead code noticed, mention it — don't delete it.
- Remove only imports/variables/functions YOUR changes made unused.
- Every changed line must trace directly to the user's request.

## 4. Goal-Driven Execution

Transform tasks into verifiable goals before coding:
- "Fix the bug" → write a test that reproduces it, then make it pass.
- "Add validation" → write tests for invalid inputs, then make them pass.

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

## Project-Specific Rules

- AGS codes are always TEXT — never cast to integer (leading-zero bug).
- SQL column names must never be interpolated from user input — use allowlist + assert.
- All ETL inserts must be idempotent (ON CONFLICT DO NOTHING or DO UPDATE).
- Per-indicator try/except: one bad indicator must not abort the whole ETL run.
- Unknown state abbreviation in API params → 422, not silent full-scan.
