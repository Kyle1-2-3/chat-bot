# Hamburger Drawer Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop left rail + mobile bottom bar with a single Gemini-style top-left hamburger button that opens a slide-in drawer (Chat/Map), on all screen sizes.

**Architecture:** Single-file change to `static/index.html` (markup + CSS + inline JS). The existing `showView()` switcher is kept; drawer items call it and close the drawer. Verification is a headless-Chrome probe (puppeteer-core driving the installed Google Chrome) run before (RED) and after (GREEN) the change.

**Tech Stack:** Plain HTML/CSS/JS, puppeteer-core for verification. Spec: `docs/superpowers/specs/2026-06-11-hamburger-drawer-nav-design.md`.

---

### Task 1: Verification probe (RED)

**Files:**
- Create: `/tmp/drawer-probe/probe.mjs` (throwaway tooling, not committed)

- [ ] **Step 1: Set up puppeteer-core in a temp dir**

```bash
mkdir -p /tmp/drawer-probe && cd /tmp/drawer-probe && npm init -y >/dev/null && npm i --silent puppeteer-core
```

- [ ] **Step 2: Write the probe**

Create `/tmp/drawer-probe/probe.mjs`:

```js
import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const URL = "file:///Users/kyle/Documents/chat-bot/static/index.html";
const fails = [];
const ok = (name, cond) => { console.log((cond ? "PASS " : "FAIL ") + name); if (!cond) fails.push(name); };
const settle = () => new Promise(r => setTimeout(r, 350)); // outlast the 200ms drawer transition
const drawerVis = (page) => page.$eval("#drawer", el => getComputedStyle(el).visibility);

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
for (const [label, vp] of [["mobile", { width: 390, height: 844 }], ["desktop", { width: 1280, height: 800 }]]) {
  const page = await browser.newPage();
  await page.setViewport(vp);
  await page.goto(URL);

  ok(label + ": old sidebar gone", await page.$(".sidebar") === null);
  const btn = await page.$("#menuBtn");
  const bb = btn && await btn.boundingBox();
  ok(label + ": hamburger fixed top-left", !!bb && bb.x < 30 && bb.y < 30);
  if (label === "mobile") {
    const dockBottom = await page.$eval(".composer-dock", el => el.getBoundingClientRect().bottom);
    ok("mobile: composer flush to bottom", Math.abs(dockBottom - vp.height) < 2);
  }
  if (!bb) { await page.close(); continue; } // rest needs the button

  ok(label + ": drawer hidden initially", await drawerVis(page) === "hidden");
  await btn.click(); await settle();
  ok(label + ": drawer opens", await drawerVis(page) === "visible");
  ok(label + ": chat item active", await page.$eval("#navChat", el => el.classList.contains("is-active")));
  ok(label + ": aria-expanded true", await page.$eval("#menuBtn", el => el.getAttribute("aria-expanded") === "true"));
  await page.screenshot({ path: `/tmp/drawer_${label}_open.png` });

  await page.keyboard.press("Escape"); await settle();
  ok(label + ": Esc closes", await drawerVis(page) === "hidden");

  await btn.click(); await settle();
  await page.click("#navMap"); await settle();
  ok(label + ": map view shown", await page.$eval("#mapView", el => !el.hidden));
  ok(label + ": drawer closed after pick", await drawerVis(page) === "hidden");
  const searchLeft = await page.$eval("#mapSearch", el => el.getBoundingClientRect().left);
  ok(label + ": map search clear of hamburger", searchLeft >= bb.x + bb.width);
  await page.screenshot({ path: `/tmp/drawer_${label}_map.png` });

  await page.click("#menuBtn"); await settle();
  await page.mouse.click(vp.width - 40, vp.height / 2); await settle();
  ok(label + ": scrim click closes", await drawerVis(page) === "hidden");
  await page.close();
}
await browser.close();
console.log(fails.length ? `\n${fails.length} FAILED` : "\nALL PASS");
process.exit(fails.length ? 1 : 0);
```

- [ ] **Step 3: Run it — must FAIL (current page still has the sidebar, no #menuBtn)**

Run: `node /tmp/drawer-probe/probe.mjs`
Expected: `FAIL mobile: old sidebar gone`, `FAIL mobile: hamburger fixed top-left`, `FAIL mobile: composer flush to bottom` (dock sits 64px up), same for desktop; exit code 1.

---

### Task 2: Implement markup + CSS + JS in `static/index.html`

**Files:**
- Modify: `static/index.html` (CSS ~lines 47, 220-242, 289-305; markup ~lines 315-324; JS ~lines 563-576)

- [ ] **Step 1: Remove the rail width variable**

Delete this line from the `:root` block (line ~47):

```css
    --rail-w: 68px;
```

- [ ] **Step 2: Replace the sidebar CSS block**

Replace everything from `/* ---------------- Sidebar (view switcher) ---------------- */` through `.app, .map-view { margin-left: var(--rail-w); }` (lines ~221-242) with:

```css
  /* ---------------- Menu button + drawer (view switcher) ---------------- */
  .menu-btn {
    position: fixed; z-index: 50;
    top: calc(10px + env(safe-area-inset-top));
    left: calc(12px + env(safe-area-inset-left));
    width: 44px; height: 44px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    border: 1px solid var(--line); cursor: pointer;
    background: var(--header); color: var(--text-muted);
    -webkit-backdrop-filter: saturate(160%) blur(18px);
    backdrop-filter: saturate(160%) blur(18px);
  }
  .menu-btn svg { width: 22px; height: 22px; }
  .menu-btn:hover { background: var(--surface-2); color: var(--text); }
  .menu-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .scrim {
    position: fixed; inset: 0; z-index: 60;
    background: rgba(0,0,0,0.5);
    opacity: 0; pointer-events: none;
    transition: opacity 200ms ease;
  }
  .scrim.is-open { opacity: 1; pointer-events: auto; }
  .drawer {
    position: fixed; left: 0; top: 0; bottom: 0; z-index: 70;
    width: 260px; display: flex; flex-direction: column; gap: 4px;
    padding: calc(14px + env(safe-area-inset-top)) 12px 14px calc(12px + env(safe-area-inset-left));
    background: var(--surface); border-right: 1px solid var(--line);
    transform: translateX(-100%); visibility: hidden;
    transition: transform 200ms ease, visibility 0s linear 200ms;
  }
  .drawer.is-open {
    transform: translateX(0); visibility: visible;
    transition: transform 200ms ease;
  }
  .drawer__title { font-size: 15px; font-weight: 700; color: var(--text); padding: 10px 12px 14px; }
  .drawer-item {
    display: flex; align-items: center; gap: 12px;
    padding: 11px 14px; border: none; border-radius: 9999px;
    background: transparent; color: var(--text-muted); cursor: pointer; text-align: left;
    font-family: var(--font); font-size: 14px; font-weight: 600;
  }
  .drawer-item svg { width: 20px; height: 20px; flex: 0 0 auto; }
  .drawer-item:hover { background: var(--surface-2); color: var(--text); }
  .drawer-item.is-active { background: var(--accent-soft); color: var(--accent); }
  .drawer-item:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

- [ ] **Step 3: Clear the hamburger in the map header**

In `.map-head` change `padding: 12px 16px;` to:

```css
    padding: 12px 16px 12px calc(64px + env(safe-area-inset-left));
```

- [ ] **Step 4: Clean the ≤640px media query**

Inside `@media (max-width: 640px)` delete these four rules (the rest stays):

```css
    .sidebar {
      top: auto; bottom: 0; left: 0; right: 0; width: auto;
      flex-direction: row; justify-content: center; gap: 24px;
      padding: 4px 0 calc(4px + env(safe-area-inset-bottom));
      border-right: none; border-top: 1px solid var(--line);
    }
    .app, .map-view { margin-left: 0; }
    .composer-dock { bottom: 64px; }
    .map-view { height: calc(100dvh - 64px); }
```

- [ ] **Step 5: Add the drawer transition to the reduced-motion block**

Inside `@media (prefers-reduced-motion: reduce)` add:

```css
    .drawer, .scrim { transition: none; }
```

- [ ] **Step 6: Replace the sidebar markup**

Replace the whole `<nav class="sidebar" ...>...</nav>` block (lines ~315-324) with:

```html
  <button type="button" class="menu-btn" id="menuBtn" aria-label="Menu" aria-controls="drawer" aria-expanded="false">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
  </button>
  <div class="scrim" id="scrim"></div>
  <aside class="drawer" id="drawer" aria-label="Views">
    <div class="drawer__title">Brentwood Assistant</div>
    <button type="button" class="drawer-item is-active" id="navChat">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <span>Chat</span>
    </button>
    <button type="button" class="drawer-item" id="navMap">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21l-6-3V3l6 3 6-3 6 3v15l-6-3-6 3z"/><path d="M9 6v15"/><path d="M15 3v15"/></svg>
      <span>Map</span>
    </button>
  </aside>
```

(IDs `navChat`/`navMap` are kept so the view-switch JS diff stays minimal.)

- [ ] **Step 7: Replace the view-switch JS**

Replace the `// ---------------- Sidebar view switching ----------------` block (from that comment through the two `addEventListener` lines, ~563-576) with:

```js
  // ---------------- Drawer view switching ----------------
  const menuBtn    = document.getElementById("menuBtn");
  const drawerEl   = document.getElementById("drawer");
  const scrimEl    = document.getElementById("scrim");
  const navChatBtn = document.getElementById("navChat");
  const navMapBtn  = document.getElementById("navMap");
  const mapViewEl  = document.getElementById("mapView");

  function setDrawer(open) {
    drawerEl.classList.toggle("is-open", open);
    scrimEl.classList.toggle("is-open", open);
    menuBtn.setAttribute("aria-expanded", String(open));
    if (open) {
      (drawerEl.querySelector(".drawer-item.is-active") || navChatBtn).focus();
    } else {
      menuBtn.focus();
    }
  }
  menuBtn.addEventListener("click", () => setDrawer(!drawerEl.classList.contains("is-open")));
  scrimEl.addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawerEl.classList.contains("is-open")) setDrawer(false);
  });

  function showView(view) {
    const isMap = view === "map";
    appEl.style.display = isMap ? "none" : "";
    if (mapViewEl) mapViewEl.hidden = !isMap;
    navChatBtn.classList.toggle("is-active", !isMap);
    navMapBtn.classList.toggle("is-active", isMap);
  }
  navChatBtn.addEventListener("click", () => { showView("chat"); setDrawer(false); });
  navMapBtn.addEventListener("click", () => { showView("map"); setDrawer(false); });
```

---

### Task 3: Verify (GREEN)

- [ ] **Step 1: Run the probe**

Run: `node /tmp/drawer-probe/probe.mjs`
Expected: every line `PASS …`, final `ALL PASS`, exit code 0.

- [ ] **Step 2: Eyeball the screenshots**

Read `/tmp/drawer_mobile_open.png`, `/tmp/drawer_mobile_map.png`, `/tmp/drawer_desktop_open.png`, `/tmp/drawer_desktop_map.png` and check: drawer looks like the Gemini reference (panel over scrim), active item highlighted, nothing overlapping, no leftover bottom bar.

- [ ] **Step 3: Run the python suite (should be untouched)**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: `109 passed`.

---

### Task 4: Commit, deploy, live-verify

- [ ] **Step 1: Commit**

```bash
git add static/index.html
git commit -m "Replace rail/bottom-bar nav with a top-left hamburger drawer

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Merge to main and push (auto-deploys)**

```bash
git checkout main && git merge a --ff-only && git push origin main a && git checkout a
```

- [ ] **Step 3: Watch the Actions run**

Run: `gh run watch $(gh run list --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status`
Expected: test + deploy both `success`.

- [ ] **Step 4: Live-verify**

Point the probe at the live site (`const URL = "https://brentwoodchatbot.xyz/"`) and re-run.
Expected: `ALL PASS`. (Live page fetches `/chat` only on send, so the probe is unaffected.)
