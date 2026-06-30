# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Face-recognition meeting attendance system (UI and code comments are in Vietnamese).
Flow: IP camera / webcam → detect many faces per frame → identify each → auto check-in
→ report absentees. Includes anti-spoofing (liveness) to block photo/screen replay.

## Commands

```bash
pip install -r requirements.txt        # first run downloads the InsightFace buffalo_l model (~300MB, needs Internet)

python gui.py                          # PyQt6 GUI (5 tabs) — primary way to run

# CLI pipeline (each step is a subcommand of main.py):
python main.py init                    # create SQLite schema
python main.py enroll                  # enroll employees from images/ (embeddings -> ChromaDB)
python main.py meeting "Title"         # new meeting, invites ALL employees (resets check-in)
python main.py meeting "Title" --invite NV001,NV002   # invite only a subset
python main.py camera "rtsp://..." --show             # recognize from camera (use "0" for webcam)
python main.py photo path/to/frame.jpg                # recognize a single still image (test)
python main.py report                  # print report + export absentee CSV
```

There is no test suite, linter, or build step. `python main.py photo <img>` is the
fastest way to exercise the recognition path without a camera.

GPU: set `PROVIDERS = ["CUDAExecutionProvider","CPUExecutionProvider"]` in `config.py`.

## Architecture

All tunable behavior lives in `config.py` — never hardcode thresholds/paths elsewhere.

**Two storage backends, split by purpose** (`face_engine.py`, `database.py`):
- **ChromaDB** (`data/chroma`, cosine HNSW) holds face *embeddings*. Vector IDs are
  `"{employee_id}#{idx}"`; each carries `metadata={"employee_id": ...}`. Similarity =
  `1 - distance` (InsightFace embeddings are L2-normalized).
- **SQLite** (`data/hr.db`) holds *everything relational*: `employees`, `meetings`,
  `meeting_invitees`, `check_in`, `check_in_history`, `spoof_log`.

**Model engine is a process-wide singleton** (`face_engine.get_app()` /
`get_collection()`). The InsightFace model is heavy; it is loaded once and warmed up
inside the camera worker thread (not on the GUI thread) to avoid freezing the UI.

**Recognition is the same core in three callers.** `face_engine.identify()` is the single
matching function (top-2 query → `SIM_THRESHOLD` floor → `MARGIN_THRESHOLD` rejection when
rank-1 and rank-2 are too close → returns status `matched|unknown|uncertain|empty_db`).
It is invoked from:
- `recognize.process_frame()` — CLI `photo`/`camera` path.
- `gui_worker.CameraWorker._process()` — GUI path (runs in a `QThread`).
Changes to matching logic belong in `identify()`, not the callers.

**GUI threading model** (`gui.py` + `gui_worker.py`): the UI never touches the camera or
model directly. `CameraWorker(QThread)` reads frames, runs AI every `interval` seconds
(but draws/emits every frame for smooth video), and communicates only via signals:
`frame_ready(QImage)`, `face_recognized(dict)`, `status(str)`, `error(str)`.
`gui.py` has 5 tabs; `CheckinTab` and `DemoTab` both extend `BaseVideoTab` — the only
difference is `do_checkin=True` vs demo-only recognition.

## Key invariants & cross-cutting rules

- **Meetings are stateful and exclusive.** `create_meeting()` archives current `check_in`
  rows into `check_in_history`, wipes `check_in`, deactivates old meetings, then creates a
  new active one and populates `meeting_invitees`. Only one meeting is active
  (`is_active=1`); `get_active_meeting()` is how every component finds "the current meeting".
- **Check-in goes through `database.insert_check_in()` only.** It enforces invite-gating
  and de-duplication, returning `checked_in | already | not_invited | no_profile`.
  `check_in.employee_id` is `UNIQUE` + `INSERT OR IGNORE`, so a person appearing in many
  frames (or across multiple cameras pointed at the same meeting) check-ins exactly once.
- **Invitee scope drives "absent".** Reports (`report.get_absent()`) count only invited
  employees who haven't checked in. A recognized person who isn't invited is *never*
  checked in — the UI shows an "outside list" warning instead.
- **Anti-spoofing is fail-soft** (`antispoof.py`). `AntiSpoofEngine.mode` degrades:
  `model+multiframe` → `multiframe_only` (no MiniFASNet `.pth` / torch) → `disabled`
  (`ANTISPOOF_ENABLED=False`). Real faces check in; `suspect`/`spoof` levels do NOT check
  in — they are logged to `spoof_log` (GUI also saves evidence crops to
  `reports/spoof_captures/`). MiniFASNet weights are not bundled; loading is wrapped to
  never hard-fail (`antispoof_models/model_loader.py` is a stub to be completed). The
  multi-frame heuristic only meaningfully works on a video stream, not a single `photo`.

## Data setup

Employees are enrolled from a directory layout, not a UI form:
```
images/
  employees.csv          # employee_id,full_name,department,position,email,phone
  NV001/ 1.jpg 2.jpg     # 1-3 clear photos; folder name == employee_id == CSV key
```
`enroll.enroll_all()` upserts each employee into SQLite, deletes their old embeddings
(`replace=True`), then adds the largest detected face per image to ChromaDB.
