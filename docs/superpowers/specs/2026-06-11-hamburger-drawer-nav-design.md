# Hamburger Drawer Navigation — Design

2026-06-11. Replaces the current view switcher (desktop left rail + mobile
bottom bar) with a single Gemini-style pattern on **all screen sizes**: a
fixed top-left hamburger button that opens a slide-in drawer.

User decisions: drawer menu (not a direct toggle); desktop and mobile both
use it; the left rail and bottom bar are removed entirely.

## Why

The mobile bottom bar is awkward (user feedback, 2026-06-11). Unifying both
viewports on one pattern also deletes the responsive rail/bottom-bar CSS.

## UI

**Hamburger button** (`#menuBtn`)
- Fixed top-left: `top: calc(10px + env(safe-area-inset-top))`, `left: calc(12px + env(safe-area-inset-left))`, above all views (z-index over drawer scrim siblings but below the open drawer).
- 44px circle, translucent `var(--header)` background + backdrop blur + `var(--line)` border, ≡ icon (inline SVG, `currentColor`).
- `aria-label="Menu"`, `aria-expanded` kept in sync, `aria-controls="drawer"`.

**Drawer** (`#drawer`)
- Fixed left panel, 260px wide, full height, `var(--surface)`-family background, right border `var(--line)`.
- Slides in with `transform: translateX(-100%) → 0`, 200ms ease; no transition under `prefers-reduced-motion`.
- Content: app title ("Brentwood Assistant") on top, then two nav items — 💬 Chat, 🗺 Map — reusing the existing rail SVG icons, horizontal rows (icon + label), active view highlighted with `var(--accent-soft)`/`var(--accent)` like the old `.nav-btn.is-active`.
- Open state = `.is-open` class; closed drawer is inert (`visibility: hidden` after transition so it can't be tabbed into).

**Scrim** (`#scrim`)
- Fixed full-screen `rgba(0,0,0,0.5)` behind the drawer, fades with it; click closes the drawer.

**Behavior**
- Hamburger click toggles the drawer.
- Selecting an item calls the existing `showView("chat"|"map")` and closes the drawer.
- `Escape` closes. On open, focus moves to the active drawer item; on close, focus returns to the hamburger button.

## Removals / layout fixes

- Delete `.sidebar` markup and all `.sidebar`/`.nav-btn` CSS, including the ≤640px bottom-bar overrides.
- `.app, .map-view { margin-left: var(--rail-w) }` → gone (no rail). `--rail-w` var removed if unused elsewhere.
- Mobile: `.composer-dock` back to `bottom: 0` (keeps its existing safe-area padding); `.map-view` back to `100dvh`.
- `.map-head` gets `padding-left: 68px` (all sizes) so the map search input doesn't sit under the fixed hamburger. Chat content scrolls under the floating button by design (same as Gemini).

## Out of scope

No new views, no server changes, no chat-header bar. Building search, map
pins, chat logic untouched.

## Verification

Headless Chrome probes, both 390×844 (mobile) and 1280×800 (desktop):
1. No bottom bar / left rail; composer flush to bottom on mobile.
2. Hamburger visible top-left; click → drawer + scrim visible, Chat marked active.
3. Click Map item → map view shown, chat hidden, drawer closed.
4. Esc and scrim click close the drawer.
5. Map search input not overlapped by the hamburger (bounding boxes don't intersect).
