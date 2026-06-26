# SMTM — Diagnose & report wrong detections

How users tell us a scan got something wrong. The app is **read-only**: a user never
edits the link map locally, because a single wrong result can stem from several different
faults and the app can't tell them apart. The user's job is to **flag**; ours is to
**diagnose** (offline) and fix the right layer.

Status: **spec / not yet implemented.** Builds on the existing inspector
(`app/frontend/inspect.html`) and the icon-hash provenance from `docs/PACKAGING.md`.

## Why read-only (the failure modes)

A "wrong" result is at least three different bugs. Letting a user "correct" it locally
papers over one with a fix meant for another:

| What actually went wrong | Layer at fault | Fix |
|---|---|---|
| **Detector wrong** — YOLO emitted the wrong icon-id, or a false/missed box | the model | add the crop as training data → retrain |
| **Link wrong** — icon-id was right, but `icon-id → item` maps to the wrong item | our lookup table | correct the curated baseline link map → ship in next archive |
| **Icon changed** — Tarkov changed the art for that icon-id since training | neither (drift) | retrain on the new icons |

We can only tell which one it is by looking at the **evidence** — the crop, the icon-id,
what we showed, and a hash of the user's current icon vs. the trained one. That's what the
report carries.

## The diagnose page

An evolution of the inspector (`/inspect`), not a new tool — it already has pan/zoom, the
detection-box overlay (green = identified, red = unidentified), box tooltips
(`#icon_id · item · source certainty`), and a draw-a-box "mark missed" gesture. The
diagnose page keeps those gestures but changes the **verb from *fix* → *report*** (nothing
writes to the link map).

### Gestures
- **Click a detected box → report menu:**
  - **⚑ Wrong item** — box/icon detected, but the named item is wrong (→ detector *or* link bug).
  - **✕ Not an item** — false positive; this box isn't an item (→ precision bug).
  - **? What is it?** *(optional)* — search the catalog to add a non-authoritative hint.
- **Draw / "fat pen" over an empty area → report missed item:** scribble or drag over a
  thing the detector missed (→ recall bug). A freehand stroke is reduced to its **bounding
  box** so we still get a clean crop; multiple strokes = multiple misses.

### Principles
- **Never require the user to know the right answer.** Every gesture works with zero
  knowledge ("this is wrong" / "something's here"); naming the correct item is always optional.
- **Batch, don't chatter.** The user marks several issues on one screenshot, then hits
  **Submit report once** → a single bundle with full context (the screenshot + every box +
  their flags). Fewer network calls, richer for triage.
- **Read-only.** Reports are the only output; the local link map is never mutated.

## What a report contains

A report is **one bundle per submitted screenshot** (the batch), carrying enough evidence
for offline triage. Crops can be derived server-side from `box` + the screenshot, but we
include them so a report is self-contained.

```jsonc
{
  "report_id": "uuid",
  "ts": "2026-06-26T...",          // when reported
  "app_version": "0.1.0",
  "model": { "name": "barry", "version": "v3",
             "icons_fingerprint": "b2a2d2ab…" },   // which model produced this scan
  "session_ts": "20260625-222833", // the scan this refers to
  "scan_summary": { "detections": 100, "identified": 100, "unidentified": 0 },

  "screenshot": "raw.png",         // whole-shot OR omitted (see privacy fork below)

  "flags": [
    {
      "type": "wrong_item",        // wrong_item | not_an_item | missed
      "box": [x0, y0, x1, y1],
      "crop_png": "<base64 / file>",          // the detected box pixels — the gold field

      // present for wrong_item / not_an_item (an existing detection):
      "detection": { "icon_id": "1234", "det_conf": 0.81 },
      "shown":     { "item_id": "5447…", "name": "Colt M4A1",
                     "source": "yolo", "certainty": 0.9 },   // what we displayed
      "user_icon_hash": { "sha256": "…", "dhash": "…" },      // user's cache icon for icon_id NOW

      // optional, any type — a HINT, never authoritative:
      "suggested_item_id": "5448…",
      "note": "free text"
    }
    // … more flags
  ]
}
```

### Field rationale (what each field unlocks)
- **`crop_png`** — the single most valuable field: lets a human/better model see what the
  thing actually is, and is direct training data.
- **`detection.icon_id` + `shown`** — what the model emitted vs. what we displayed; the gap
  is the bug. `source`/`certainty` already hint at the layer (high-certainty YOLO but wrong
  → likely link bug; low certainty → likely detector).
- **`user_icon_hash`** vs. the model's trained `icon_hashes.json` for that `icon_id`:
  - matches trained hash, but item wrong → **link table** bug.
  - differs from the crop's content / trained hash → **detector** bug.
  - differs from our **trained** hash → Tarkov **changed the icon** (drift) → retrain.
- **`model.icons_fingerprint`** — ties the report to the exact model build that produced it.
- **`suggested_item_id`** — speeds triage but is verified, never trusted (read-only ethos).

## Triage (server-side, later)

Reports land in a queue we review. Per flag: identify the true item from `crop_png`, then
use the hash comparison above to route it to **retrain** (detector/drift) or **link-map fix**
(curated baseline, re-shipped per `docs/PACKAGING.md`). Confirmed link fixes update the
baseline `links/` we ship; confirmed detector misses become labeled training crops.

## Transport

- **Now:** queue reports locally (e.g. `reports/<ts>/`), no server required.
- **Later:** POST the bundle to a collection endpoint (opt-in). Design TBD (auth, dedupe,
  moderation, rate-limiting) — out of scope here.

## Open decision: privacy of the screenshot

The batch bundle is richest if it includes the **whole annotated screenshot** (full context,
neighboring items) — but that reveals the user's entire stash. The alternative is shipping
**only the flagged crops** (private, less context). Leaning: whole-shot with an explicit
opt-in toggle; default to crops-only if the user prefers. **Not yet decided.**
