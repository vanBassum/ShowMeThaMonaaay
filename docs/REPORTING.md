# SMTM — Diagnose & report wrong detections

How users tell us a scan got something wrong. The app is **read-only**: a user never edits
the link map, because a single wrong result can stem from several different faults and the
app can't tell them apart. The user's job is to **flag**; ours is to **diagnose** (offline)
and fix the right layer.

Status: **partly built** — see "What's built vs pending" at the bottom. This is the
authoritative design; the feat branch already implements the analysis/flagging half.

## Why read-only (the failure modes)

A "wrong" result is at least three different bugs. A local "correct it" papers over one
with a fix meant for another:

| What actually went wrong | Layer at fault | Fix |
|---|---|---|
| **Detector wrong** — YOLO emitted the wrong icon-id, or a false/missed box | the model | add the crop as training data → retrain |
| **Link wrong** — icon-id right, but `icon-id → item` maps to the wrong item | our lookup table | correct the curated baseline link map → ship in next archive |
| **Icon changed** — Tarkov changed the art for that icon-id since training | neither (drift) | retrain on the new icons |

We tell them apart from the **evidence**: the crop, the icon-id, what was shown, and a hash
of the user's current icon vs. the trained one (see `docs/PACKAGING.md`, `icon_hashes.json`).

## The diagnose flow (built)

The analysis page (`app/smtm-ui/.../analysis/AnalysisPanel.tsx` + `CorrectionDialog.tsx`)
is the diagnose view: a session's screenshot + detection overlay, where you **click a box →
search the catalog → flag what it should be** (and propagate the flag to same-icon-id boxes).
It never edits the link map — flags are saved per session.

- **Storage:** `GET/POST /api/session/<ts>/fixes` → one `fixes.json` (`{ts, flags[]}`) per
  session, in the AppData session dir. Each flag = "this box should be item X / not an item".
- **Read-only:** fixes never touch the link map (server comment: *"a shareable report is
  built from these in a later step"*).

### Principle
**Never require the user to know the right answer.** Flagging "this is wrong" / "something's
missing here" must work with zero knowledge; naming the correct item stays optional.

## What a report contains

A **report** is the shareable artifact built *from* a session's fixes — enough evidence for
offline triage. One bundle per session:

```jsonc
{
  "report_id": "uuid", "ts": "...",            // server-receipt time = the canonical clock
  "app_version": "...",
  "model": { "name": "barry", "version": "v3",
             "icons_fingerprint": "b2a2d2ab…" }, // which model produced the scan
  "session_ts": "20260625-222833",
  "flags": [
    { "type": "wrong_item|not_an_item|missed",
      "box": [x0,y0,x1,y1],
      "crop_png": "<the box pixels — the gold field>",
      "detection": { "icon_id": "1234", "det_conf": 0.81 },   // wrong_item / not_an_item
      "shown":     { "item_id": "…", "name": "…", "source": "yolo", "certainty": 0.9 },
      "user_icon_hash": { "sha256": "…", "dhash": "…" },       // user's cache icon for icon_id NOW
      "suggested_item_id": "…"                                 // optional HINT, never authoritative
    }
  ]
}
```

Triage routing: compare `crop`/`user_icon_hash` to the trained `icon_hashes.json` for that
`icon_id` → match-but-wrong-item = **link** bug; no-match = **detector** bug; differs from
*trained* hash = **drift**. Confirmed link fixes update the curated baseline and re-ship
(`docs/PACKAGING.md`); detector misses become training crops.

## Transport

- **Now:** reports stage locally — `app/backend/paths.py` already reserves `reports_dir()`
  (AppData). Build a "shareable report from fixes" step + a local export (a zip for a GitHub
  issue / DM) to validate the schema before any server.
- **Later:** `POST` the bundle to a collection endpoint. The exe is public → **no client
  secret**; design for spam tolerance (size/rate limits, validate `icons_fingerprint`).
  Serverless (Worker + object storage) is the cheap path. Out of scope until there are users.

## Dogfood loop (single-user first)

The dev is both first *user* and *curator*. Reports stage locally; a tool folds confirmed
fixes back into the shipped package.

- **Part 1 — capture (mostly built):** analysis editor + per-session `fixes.json` (read-only)
  exist. *Pending:* assemble a **report bundle** from fixes (add `crop_png`, `detection`,
  `shown`, `user_icon_hash`, model fingerprint) into `reports_dir()`.
- **Part 2 — assessor (to build):** `tools/apply_reports.py` walks staged reports, curator
  confirms; **link** fixes append to the curated baseline (`<training>/links/links.jsonl` as
  `manual` events), **detector** ones route to training crops; then `tools/pack_model.py`
  cuts a new package. Link-only fixes need no retrain (see PACKAGING.md links-update path).

## Reports → model provenance

Each model records a **`reports_cutoff`** in its `manifest.json` (frozen at the *start* of
retraining): reports with `ts ≤ cutoff` were folded in; anything later rolls to the next
model. Reasoned within an `icons_fingerprint` lineage. Full spec in `docs/PACKAGING.md`.

## What's built vs pending (feat branch)

**Built:** analysis/diagnose page + `CorrectionDialog`; per-session `fixes.json` (read-only,
`/api/session/<ts>/fixes`); AppData routing incl. `reports_dir()`; model+links
download-from-release + fingerprint (`backend/models.py`); **read-only enforced** — the
legacy `/api/override` + `add_manual_link` write path was removed, and `scan.py` reads the
link map straight from the model package (no runtime writes).

**Pending:**
- Build the **report bundle** from fixes (crop + evidence + fingerprint) → `reports_dir()`.
- `tools/apply_reports.py` assessor → baseline links → repackage.
- Report **transport** (local export → server endpoint).
- `reports_cutoff` in the manifest + `pack_model.py`.
- A separate **user-override store** keyed to `icons_fingerprint`, if/when in-app
  corrections return (the read-only baseline must stay pristine; see TODO.md).

## Open decision: screenshot privacy

Whole annotated screenshot (richest context, reveals the stash) vs. flagged crops only
(private, less context). Leaning: crops-only by default, whole-shot opt-in. **Not decided.**
