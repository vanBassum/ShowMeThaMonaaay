# ShowMeThaMonaaay — project instructions

Tarkov inventory valuer: screenshot → detect items → identify → rank by ₽/slot.
See `docs/STRUCTURE.md` for architecture and current state.

## Logbook (LM / model work only)

`LOGBOOK.md` is **scoped to the learning-model work** — detector/model experiments:
synthetic data, training runs, augmentations, packaging, eval on real shots. It exists
so we can see what worked and avoid re-trying dead ends. **Do NOT log UX / app
plumbing / frontend / backend-wiring work here** (use `docs/TODO.md` for deferred app
work, commit messages for the rest).

- After any meaningful **model experiment** (a new approach, a tuning pass, a result),
  **append a dated entry to `LOGBOOK.md`** — no need to ask.
- Each entry: **date**, **what we tried**, **why**, **result (worked / didn't /
  partial)**, and **next/decision**. Be honest about failures — that's the point.
- Newest entries at the top. Keep entries short; link commits/branches/files.
