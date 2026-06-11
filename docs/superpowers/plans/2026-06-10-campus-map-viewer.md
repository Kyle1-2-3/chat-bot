# Campus Map Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a left sidebar to the chat UI that switches to a campus-map view with building search (pin + pulse highlight); later, a `LOCATION` intent that points students to the map.

**Architecture:** All Phase-1 work is inside the existing single-file frontend `static/index.html` (Flask serves it; no build step). The map view is a hidden sibling of the chat `.app` container — a sidebar button swaps `display`, so chat state survives. Building search is a hardcoded JS array with percentage coordinates over the map image. Phase 2 adds a `LOCATION` intent to the existing Gemini classifier pipeline in `app.py`.

**Tech Stack:** Vanilla HTML/CSS/JS (no libraries). Backend: Flask + Gemini classifier, pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-campus-map-viewer-design.md`

**⚠️ Repo coordination:** Another agent is concurrently editing `sync_schedule.py` / `tests/test_sync_schedule.py`. Never `git add -A` or `git add .` — stage only the exact files listed in each commit step. **Task 6 (Phase 2) touches `app.py` and is DEFERRED — do not execute it until the user confirms the other agent is done.** Do not push (push to main auto-deploys).

---

### Task 1: Add the map image asset

**Files:**
- Create: `static/campus-map.png` (copy of `/Users/kyle/Desktop/jinja map.png`, 1536×1024)

- [ ] **Step 1: Copy the image**

```bash
cp "/Users/kyle/Desktop/jinja map.png" static/campus-map.png
```

- [ ] **Step 2: Verify**

Run: `sips -g pixelWidth -g pixelHeight static/campus-map.png`
Expected: `pixelWidth: 1536`, `pixelHeight: 1024`

- [ ] **Step 3: Commit**

```bash
git add static/campus-map.png
git commit -m "Add campus map image asset"
```

---

### Task 2: Sidebar + view switching

**Files:**
- Modify: `static/index.html` (CSS block ~line 220, HTML body ~line 237, JS ~line 282 and end of script)

- [ ] **Step 1: Add `--rail-w` CSS variable**

In the `:root` block, after the line `--dock-h: 96px;` (line ~46), add:

```css
    --rail-w: 68px;
```

- [ ] **Step 2: Add sidebar + view-switch CSS**

Insert immediately BEFORE the `/* ---------------- Responsive ---------------- */` comment (line ~220):

```css
  /* ---------------- Sidebar (view switcher) ---------------- */
  .sidebar {
    position: fixed; left: 0; top: 0; bottom: 0; z-index: 40;
    width: var(--rail-w);
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    padding: 14px 0;
    background: var(--header);
    -webkit-backdrop-filter: saturate(160%) blur(18px);
    backdrop-filter: saturate(160%) blur(18px);
    border-right: 1px solid var(--line);
  }
  .nav-btn {
    width: 52px; padding: 8px 0 6px; border: none; border-radius: 14px;
    background: transparent; color: var(--text-muted); cursor: pointer;
    display: flex; flex-direction: column; align-items: center; gap: 3px;
    font-family: var(--font); font-size: 11px; font-weight: 600;
  }
  .nav-btn svg { width: 22px; height: 22px; }
  .nav-btn:hover { background: var(--surface-2); color: var(--text); }
  .nav-btn.is-active { background: var(--accent-soft); color: var(--accent); }
  .nav-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .app, .map-view { margin-left: var(--rail-w); }
```

- [ ] **Step 3: Add mobile rules for the sidebar**

Inside the existing `@media (max-width: 640px)` block (line ~221), append:

```css
    .sidebar {
      top: auto; bottom: 0; left: 0; right: 0; width: auto;
      flex-direction: row; justify-content: center; gap: 24px;
      padding: 4px 0 calc(4px + env(safe-area-inset-bottom));
      border-right: none; border-top: 1px solid var(--line);
    }
    .app, .map-view { margin-left: 0; }
    .composer-dock { bottom: 64px; }
```

- [ ] **Step 4: Add sidebar HTML**

Immediately after `<body>` (line ~236), BEFORE `<div class="app">`, insert:

```html
  <nav class="sidebar" aria-label="Views">
    <button type="button" class="nav-btn is-active" id="navChat">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <span>Chat</span>
    </button>
    <button type="button" class="nav-btn" id="navMap">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21l-6-3V3l6 3 6-3 6 3v15l-6-3-6 3z"/><path d="M9 6v15"/><path d="M15 3v15"/></svg>
      <span>Map</span>
    </button>
  </nav>
```

- [ ] **Step 5: Add view-switch JS**

At the END of the `<script>` block, just before the final three init lines (`appEl.classList.add("app--welcome"); ...`), insert:

```js
  // ---------------- Sidebar view switching ----------------
  const navChatBtn = document.getElementById("navChat");
  const navMapBtn  = document.getElementById("navMap");
  const mapViewEl  = document.getElementById("mapView");

  function showView(view) {
    const isMap = view === "map";
    appEl.style.display = isMap ? "none" : "";
    if (mapViewEl) mapViewEl.hidden = !isMap;
    navChatBtn.classList.toggle("is-active", !isMap);
    navMapBtn.classList.toggle("is-active", isMap);
  }
  navChatBtn.addEventListener("click", () => showView("chat"));
  navMapBtn.addEventListener("click", () => showView("map"));
```

(`mapViewEl` is null until Task 3 adds the element — the `if` guard keeps Task 2 testable on its own.)

- [ ] **Step 6: Verify in browser**

Run: `open static/index.html`
Check: left rail with Chat/Map buttons; Chat is highlighted; clicking Map hides the chat (blank main area is OK for now); clicking Chat brings the welcome screen back; typing in the composer still works. Narrow the window below 640px: rail moves to the bottom edge.

- [ ] **Step 7: Commit**

```bash
git add static/index.html
git commit -m "Add left sidebar with chat/map view switching"
```

---

### Task 3: Map view markup + styles

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add map view CSS**

Insert immediately after the sidebar CSS block added in Task 2 Step 2 (still before the Responsive comment):

```css
  /* ---------------- Map view ---------------- */
  .map-view { height: 100dvh; display: flex; flex-direction: column; }
  .map-head {
    flex: 0 0 auto; display: flex; align-items: center; gap: 12px;
    padding: 12px 16px;
    background: var(--header);
    -webkit-backdrop-filter: saturate(160%) blur(18px);
    backdrop-filter: saturate(160%) blur(18px);
    border-bottom: 1px solid var(--line);
  }
  #mapSearch {
    flex: 0 1 360px; min-width: 0;
    font-family: var(--font); font-size: 16px; color: var(--text);
    background: var(--surface); border: 1px solid var(--line); border-radius: 9999px;
    padding: 9px 18px; outline: none;
  }
  #mapSearch:focus { border-color: rgba(255,255,255,0.22); }
  #mapSearch::placeholder { color: var(--text-dim); }
  .map-status { font-size: 13px; font-weight: 500; color: var(--text-dim); white-space: nowrap; }
  .map-status.is-error { color: var(--warn); }
  .map-stage { flex: 1 1 auto; overflow: auto; padding: 16px; }
  .map-canvas { position: relative; max-width: 1200px; min-width: 720px; margin: 0 auto; }
  .map-canvas img { display: block; width: 100%; border-radius: 14px; user-select: none; -webkit-user-select: none; }
  .map-pin { position: absolute; width: 16px; height: 16px; transform: translate(-50%, -50%); pointer-events: none; }
  .map-pin__dot {
    display: block; width: 16px; height: 16px; box-sizing: border-box;
    background: var(--accent); border: 3px solid #fff; border-radius: 50%;
    box-shadow: 0 0 0 0 rgba(59,130,246,0.55);
    animation: pin-pulse 1.6s infinite;
  }
  @keyframes pin-pulse {
    0%   { box-shadow: 0 0 0 0 rgba(59,130,246,0.55); }
    70%  { box-shadow: 0 0 0 18px rgba(59,130,246,0); }
    100% { box-shadow: 0 0 0 0 rgba(59,130,246,0); }
  }
  .map-pin__label {
    position: absolute; top: 22px; left: 50%; transform: translateX(-50%);
    padding: 3px 10px; border-radius: 9999px;
    background: rgba(23,24,28,0.88); border: 1px solid var(--line);
    color: var(--text); font-size: 12px; font-weight: 600; white-space: nowrap;
  }
  @media (max-width: 640px) {
    .map-view { height: calc(100dvh - 64px); }
  }
  @media (prefers-reduced-motion: reduce) {
    .map-pin__dot { animation: none; }
  }
```

- [ ] **Step 2: Add map view HTML**

Immediately after the closing `</div>` of `<div class="app">` (line ~268, before `<script>`), insert:

```html
  <!-- Campus map view -->
  <section class="map-view" id="mapView" hidden aria-label="Campus map">
    <div class="map-head">
      <label for="mapSearch" class="sr-only">Search a building</label>
      <input id="mapSearch" type="search" placeholder="Search a building&hellip;" autocomplete="off" spellcheck="false" />
      <span class="map-status" id="mapStatus" aria-live="polite"></span>
    </div>
    <div class="map-stage">
      <div class="map-canvas">
        <img src="campus-map.png" alt="Brentwood College School campus map" draggable="false" />
        <div class="map-pin" id="mapPin" hidden>
          <span class="map-pin__dot"></span>
          <span class="map-pin__label" id="mapPinLabel"></span>
        </div>
      </div>
    </div>
  </section>
```

- [ ] **Step 3: Verify in browser**

Run: `open static/index.html`
Check: clicking Map now shows the search input + the campus map image, dark-theme styled; clicking Chat returns to chat with prior state intact. Narrow window: map pans horizontally (min-width 720px forces scroll instead of unreadable shrink).

- [ ] **Step 4: Commit**

```bash
git add static/index.html
git commit -m "Add campus map view with search header and pin overlay"
```

---

### Task 4: Building data + search logic

**Files:**
- Modify: `static/index.html` (JS, after the view-switch block from Task 2)

- [ ] **Step 1: Add building data + search JS**

Insert after the view-switch JS block (before the final init lines):

```js
  // ---------------- Campus map search ----------------
  // x/y are percentages of the map image (1536x1024). Calibrated by eye; see plan Task 4.
  const BUILDINGS = [
    { name: "Crooks Hall", aliases: ["dining hall", "cafeteria", "student centre", "student center", "fitness centre", "fitness center", "tuck shop", "laundry"], x: 25.6, y: 77.0 },
    { name: "Campbell Common", aliases: ["common"], x: 32.7, y: 78.0 },
    { name: "Centre for Arts & Humanities", aliases: ["humanities", "arts and humanities"], x: 39.5, y: 78.5 },
    { name: "Centre for Innovation and Learning", aliases: ["innovation", "cfil"], x: 55.0, y: 77.5 },
    { name: "TGB Centre for Performing Arts", aliases: ["performing arts", "theatre", "theater", "tgb"], x: 29.3, y: 64.0 },
    { name: "Hope House", aliases: [], x: 28.6, y: 45.5 },
    { name: "Allard House", aliases: [], x: 35.2, y: 52.5 },
    { name: "Mackenzie House", aliases: [], x: 42.6, y: 55.5 },
    { name: "Alex House", aliases: [], x: 51.4, y: 62.8 },
    { name: "Rogers House", aliases: [], x: 55.5, y: 45.8 },
    { name: "Whittall House", aliases: [], x: 63.5, y: 53.0 },
    { name: "Ellis House", aliases: [], x: 72.4, y: 46.8 },
    { name: "Privett House", aliases: [], x: 70.0, y: 56.7 },
    { name: "Woodward", aliases: ["admin", "administration", "admissions"], x: 83.8, y: 45.3 },
    { name: "Maeda Health Centre", aliases: ["health", "nurse", "clinic", "maeda"], x: 79.0, y: 51.5 },
    { name: "Foote Athletic Centre", aliases: ["gym", "athletics", "foote"], x: 84.0, y: 16.5 },
    { name: "Artificial Turf", aliases: ["turf"], x: 85.3, y: 33.5 },
    { name: "Field 1", aliases: [], x: 23.4, y: 23.0 },
    { name: "Field 2", aliases: [], x: 37.8, y: 13.5 },
    { name: "Field 3 (Gillespie Field)", aliases: ["gillespie"], x: 56.6, y: 29.5 },
    { name: "Field 4", aliases: [], x: 69.5, y: 29.0 },
    { name: "Tennis Courts", aliases: ["tennis"], x: 38.3, y: 29.0 },
    { name: "Main Gate", aliases: ["gate", "entrance"], x: 48.0, y: 8.5 },
    { name: "Grounds", aliases: [], x: 62.3, y: 8.8 },
    { name: "Dock Area", aliases: ["dock", "waterfront", "pier"], x: 54.5, y: 93.5 },
    { name: "Visitor Parking", aliases: ["parking"], x: 21.0, y: 51.0 },
  ];

  const mapSearchEl = document.getElementById("mapSearch");
  const mapStatusEl = document.getElementById("mapStatus");
  const mapPinEl    = document.getElementById("mapPin");
  const mapPinLabel = document.getElementById("mapPinLabel");

  function findBuilding(query) {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return null;
    return BUILDINGS.find(b =>
      b.name.toLowerCase().includes(q) ||
      b.aliases.some(a => a.includes(q) || q.includes(a))
    ) || null;
  }

  mapSearchEl.addEventListener("input", () => {
    const raw = mapSearchEl.value;
    if (!raw.trim()) {
      mapPinEl.hidden = true;
      mapStatusEl.textContent = "";
      mapStatusEl.classList.remove("is-error");
      return;
    }
    const hit = findBuilding(raw);
    if (hit) {
      mapPinEl.style.left = hit.x + "%";
      mapPinEl.style.top  = hit.y + "%";
      mapPinLabel.textContent = hit.name;
      mapPinEl.hidden = false;
      mapStatusEl.textContent = hit.name;
      mapStatusEl.classList.remove("is-error");
    } else {
      mapPinEl.hidden = true;
      mapStatusEl.textContent = "No matching building";
      mapStatusEl.classList.add("is-error");
    }
  });
```

- [ ] **Step 2: Add temporary calibration helper**

Insert directly after the block above:

```js
  // TEMP calibration helper — REMOVE before commit of Step 5
  document.querySelector(".map-canvas img").addEventListener("click", (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    console.log(
      (((e.clientX - r.left) / r.width) * 100).toFixed(1),
      (((e.clientY - r.top) / r.height) * 100).toFixed(1)
    );
  });
```

- [ ] **Step 3: Calibrate coordinates**

Run: `open static/index.html`, switch to Map, open DevTools console.
For EVERY entry in `BUILDINGS`: click the center of that building on the image, read the logged `x y`, and update the entry if it differs from the hardcoded value by more than ~1.5 points. (The hardcoded values are estimates read off the image; most should be close.)

- [ ] **Step 4: Verify search behavior**

In the Map view search box, check each case:
- `crooks` → pin on Crooks Hall, status "Crooks Hall"
- `dining hall` → pin on Crooks Hall (alias)
- `the tuck shop` → pin on Crooks Hall (query-contains-alias direction)
- `gym` → pin on Foote Athletic Centre
- `gillespie` → pin on Field 3
- `zzz` → no pin, "No matching building" in warn color
- clear the input → pin and status disappear
- Resize the window: pin stays glued to the same building (percentage coords)

- [ ] **Step 5: Remove the calibration helper**

Delete the TEMP block added in Step 2. Re-open the page and spot-check one search (`crooks`) still works.

- [ ] **Step 6: Commit**

```bash
git add static/index.html
git commit -m "Add building search with pin highlight to campus map"
```

---

### Task 5: Full manual verification pass (Phase 1 done)

**Files:** none (verification only)

- [ ] **Step 1: Chat regression**

Run the backend if available (`python3 app.py`) and open `http://127.0.0.1:5000/static/index.html` — otherwise `open static/index.html` (chat send will fail without the server; the retry UI appearing IS the expected behavior in that case).
Check: send a message (or see the retry affordance), switch to Map, switch back — the conversation log is still there; composer focus/counter still work.

- [ ] **Step 2: Mobile layout**

DevTools device toolbar at 375×812:
- Sidebar is a bottom bar; composer sits above it, not hidden behind it
- Map view fits, image pans horizontally, pin lands correctly
- Welcome screen still roughly centered

- [ ] **Step 3: Report**

Report results to the user, including any coordinate corrections made in Task 4 Step 3. Phase 1 complete — STOP here. Do not start Task 6 without explicit user go-ahead (another agent may still be working in the repo).

---

### Task 6: `LOCATION` intent (PHASE 2 — DEFERRED)

**⛔ Do not execute until the user confirms the other agent is finished with the repo, then `git pull`/rebase as needed so `app.py` is current.**

**Files:**
- Create: `tests/test_location.py`
- Modify: `app.py` (4 small edits: classifier enum line ~180, classifier rules ~line 214, `VALID_INTENTS` ~line 233, `build_result_from_classification` ~line 420, `ANSWER_SYSTEM` ~line 480)

- [x] **Step 1: Write failing tests**

Create `tests/test_location.py`:

```python
from datetime import date

import app as appmod


def test_validate_keeps_location_intent():
    out = appmod.validate_request({"intent": "LOCATION"})
    assert out["intent"] == "LOCATION"


def test_build_result_location(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 6, 10))
    res = appmod.build_result_from_classification(
        {"intent": "LOCATION", "day_ref": "ANY", "meal_type": None},
        "where is crooks hall",
    )
    assert res["type"] == "LOCATION"


def test_chat_location_path(monkeypatch):
    monkeypatch.setattr(appmod, "today", lambda: date(2026, 6, 10))
    monkeypatch.setattr(appmod, "classify_query", lambda msg, memory="": [
        {"intent": "LOCATION", "day_ref": "ANY", "meal_type": None},
    ])
    captured = {}
    monkeypatch.setattr(appmod, "generate_answer",
                        lambda msg, cls, results: captured.setdefault("results", results) or "ok")

    appmod.app.test_client().post("/chat", json={"message": "where is crooks hall"})
    assert captured["results"][0]["type"] == "LOCATION"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_location.py -v`
Expected: `test_validate_keeps_location_intent` FAILS (intent coerced to `UNKNOWN`); `test_build_result_location` FAILS (`type` is `UNKNOWN`); `test_chat_location_path` may pass or fail depending on UNKNOWN filtering — that's fine, at least the first two must FAIL.

- [x] **Step 3: Add `LOCATION` to the classifier prompt**

In `CLASSIFIER_SYSTEM` (app.py line ~180), change the intent enum line to include LOCATION before UNKNOWN:

```
      "intent": "GREETING" | "MEAL" | "MEALS_DAY" | "SCHEDULE" | "MEAL_SIGNIN" | "SIGNIN_SUMMARY" | "GRADE_GROUP" | "BEDTIME" | "EVENT_SEARCH" | "LOCATION" | "UNKNOWN",
```

And in the rules list, after the EVENT_SEARCH rule (line ~213), add:

```
- If the user asks WHERE a building or place on campus is, or how to find/get to
  one — "where is Crooks Hall", "how do I get to the gym", "크룩스홀 어디야" —
  classify as LOCATION. (Asking WHEN something happens is NOT LOCATION.)
```

- [x] **Step 4: Add to VALID_INTENTS**

In `app.py` (~line 233):

```python
VALID_INTENTS = {
    "GREETING", "MEAL", "MEALS_DAY", "SCHEDULE",
    "MEAL_SIGNIN", "SIGNIN_SUMMARY", "GRADE_GROUP", "BEDTIME",
    "EVENT_SEARCH", "LOCATION", "UNKNOWN"
}
```

- [x] **Step 5: Add the build_result branch**

In `build_result_from_classification` (app.py, after the `SIGNIN_SUMMARY` branch ~line 418, before the final `return`):

```python
    if intent == "LOCATION":
        return {"type": "LOCATION"}
```

- [x] **Step 6: Add the answer rule**

In `ANSWER_SYSTEM` SPECIAL RULES (app.py, after the GREETING rule ~line 481), add:

```
- For LOCATION:
  - Tell the user every building can be found on the campus map: open it with the
    Map button in the sidebar on the left and search the building name there.
  - Do NOT give walking directions and do NOT invent building locations.
```

- [x] **Step 7: Run the new tests**

Run: `python3 -m pytest tests/test_location.py -v`
Expected: 3 passed

- [x] **Step 8: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass (pre-existing failures in the other agent's `test_sync_schedule.py`, if any, are not yours — report but don't fix)

- [x] **Step 9: Commit**

```bash
git add app.py tests/test_location.py
git commit -m "Add LOCATION intent pointing students to the campus map"
```
