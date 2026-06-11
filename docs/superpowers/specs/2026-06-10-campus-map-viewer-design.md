# Campus Map Viewer — Design

**Date:** 2026-06-10
**Status:** Approved

## Goal

Students asking "where is Crooks Hall?" should find buildings on a campus map themselves, via a dedicated map view with search — the chatbot never renders images. The chatbot only points users to the map.

## Decisions made

- **Complete separation:** chatbot does NOT show maps or pins. A new `LOCATION` intent replies with canned text directing users to the map view.
- **Left sidebar navigation** added to the existing chat UI; switches between Chat and Map views.
- **Same-page view switch** (no separate page, no reload) — chat conversation stays alive while viewing the map.
- **Map asset:** the full-campus high-res illustration (`jinja map.png`, from `~/Desktop`), which includes all athletic facilities, Main Gate, and the residential/academic core. Replaces the older hand-drawn SVG draft in `design-drafts/campus-map.html` (draft left untouched).

## Architecture

All frontend work lives in `static/index.html` (the existing single-file UI). One new static asset: `static/campus-map.png`.

### 1. Sidebar

- Slim fixed bar on the left with two items: **Chat** and **Map** (icon + label).
- Clicking toggles which view is visible (`display` swap on two container elements). No routing, no reload.
- Chat state (messages, composer) is untouched when hidden.
- Mobile (narrow viewport): sidebar collapses to a compact bottom bar or icon rail — match the existing responsive behavior of the page.
- Styling matches the existing warm-dark theme (`--surface`, `--line`, `--accent` CSS vars).

### 2. Map view

- Header: search input (placeholder e.g. "Search a building…").
- Body: the campus map image, fit to available space, horizontally scrollable/zoomable on small screens (CSS `overflow` + pinch-zoom via native behavior; no JS zoom library).
- A pin/highlight overlay layer absolutely positioned over the image, using **percentage coordinates** so it stays aligned at any rendered size.

### 3. Building search

- Hardcoded JS array of ~25 entries: `{ name, aliases[], x%, y% }`.
- Matching: case-insensitive substring over name + aliases. First match wins; show "no match" state otherwise.
- On match: drop a pin at (x%, y%) with a pulse animation and show the matched building name.
- Alias examples: `dining hall / tuck shop / laundry / fitness centre / student centre → Crooks Hall`, `gym → Foote Athletic Centre`, `admissions / admin → Woodward`, `health centre / nurse → Maeda Health Centre`, `turf → Artificial Turf`.
- Buildings covered (from the map image): Crooks Hall, Campbell Common, Centre for Arts & Humanities, Centre for Innovation and Learning, TGB Centre for Performing Arts, Hope House, Allard House, Mackenzie House, Alex House, Rogers House, Whittall House, Ellis House, Privett House, Woodward, Maeda Health Centre, Foote Athletic Centre, Artificial Turf, Field 1, Field 2, Field 3 (Gillespie Field), Field 4, Tennis Courts, Main Gate, Grounds, Dock Area.
- Coordinates measured once during implementation (percentage of image width/height).

### 4. Backend — `LOCATION` intent (deferred to phase 2)

- Add `LOCATION` to the classifier prompt enum and `VALID_INTENTS` in `app.py`.
- Handler returns canned text, e.g. "You can find any building on the campus map — open it from the sidebar on the left and search the building name."
- **Deferred** until the other agent currently working in the repo finishes, to avoid touching backend files concurrently. The map feature is fully functional without it.

## Phasing

| Phase | Scope | Files touched |
|---|---|---|
| 1 (now) | Sidebar + map view + search | `static/index.html`, `static/campus-map.png` (new) |
| 2 (later) | `LOCATION` intent | `app.py` |

## Error handling

- Search with no match: small inline "not found" hint under the input; pin hidden.
- Image fails to load: native broken-image state is acceptable (static asset served by Flask alongside index.html; same trust level).

## Testing

- Phase 1 is pure static frontend; verify manually in browser: view switching preserves chat, search hits each alias class, pin lands on the correct building at two window sizes (coordinate % correctness), mobile layout.
- Phase 2: extend existing intent tests with LOCATION classification + canned-response check.
