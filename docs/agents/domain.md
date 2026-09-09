# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This is a **single-context** repo: one `CONTEXT.md` and one `docs/adr/`, both at the root.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the glossary.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.
- **`CLAUDE.md`** at the repo root — holds the standing rules and live operational facts. The ADRs hold the reasoning behind settled decisions; `CLAUDE.md` points at them rather than repeating them, so read both.
- **`CODING_STANDARDS.md`** at the repo root — required reading before editing anything under `watchnext/` or `docker-compose.yml`.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── CONTEXT.md                 ← glossary (not created yet)
├── CLAUDE.md                  ← rules + live facts
├── CODING_STANDARDS.md        ← how code is written
├── docs/adr/
│   ├── 0001-sqlite-over-postgres.md
│   └── …
├── docker-compose.yml
└── watchnext/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
