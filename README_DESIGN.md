# Handoff: Grapefruit waitlist landing page

## Overview
Public marketing/waitlist page for Grapefruit — a biotech screener that surfaces binary
events (PDUFA dates, Phase 2/3 readouts, EMA decisions) across the US + EU small-cap
universe. Goal of the page: one clear claim, proof that the product exists (in-situ
dashboard shot + a real catalyst card), pricing, FAQ, email capture.

Target repo: **BBiering/grapefruit**, branch `main`.

## About the design files
`index.html` in this folder is a **design reference**, not a drop-in production artifact
— though it is deliberately dependency-free (plain HTML + inline/`<style>` CSS + ~8 lines
of vanilla JS), so it can also be committed as-is and iterated on.

Two sane landing paths in the repo:

1. **Static page (fastest).** Commit as `frontend/public/landing/index.html` (or repo-root
   `docs/index.html` for GitHub Pages) and serve it directly. Only change needed: wire the
   waitlist form to a real endpoint.
2. **In the React app.** Recreate it as `frontend/src/pages/Landing.tsx` using the
   existing Vite/React + `styles.css` conventions, routed at `/`, with the dashboard
   behind auth. Lift the values below rather than copying the HTML verbatim.

The page intentionally *mimics* the real dashboard chrome (topbar, filter pills, company
card, catalyst timeline). If `CompanyCard.tsx` / `MiniChart.tsx` change, the product shot
should be regenerated from the real components rather than kept as a hand-built replica.

## Fidelity
**High-fidelity.** Final colors, type scale, spacing and interaction states. Recreate
pixel-accurately; every value is listed below.

## Screens / views
Single scrolling page, seven bands, max content width `1120px` (product shot `1180px`,
FAQ `780px`), horizontal padding `24px`, section padding `110px` vertical.

### 1. Sticky header (72px tall)
- `position: sticky; top: 0; z-index: 50`, `rgba(255,255,255,.72)` +
  `backdrop-filter: blur(20px) saturate(180%)`, bottom border `1px rgba(28,26,24,.06)`.
- Left: 🍊 emoji 21px with `drop-shadow(0 2px 6px rgba(232,102,79,.35))` + wordmark
  "Grapefruit" — Playfair Display italic 600, 22px, gradient-clipped text
  `linear-gradient(135deg, #f4bd4c, #e8664f 55%, #e0537f)`.
- Nav: Product / Example / Pricing / FAQ — 14px, 500, `#6b6661`, hover `#1c1a18`, gap 26px.
- Right: pill CTA "Join the waitlist" — 14px/600, white, `9px 18px`, radius 999px,
  `linear-gradient(135deg, #e8664f, #f4bd4c)`, shadow `0 6px 18px rgba(232,102,79,.28)`;
  hover shadow `0 12px 28px rgba(232,102,79,.34)`.

### 2. Hero (padding 120/96)
- Background: three stacked radial gradients over `#fbf8f5` — gold `rgba(244,189,76,.30)`
  at `78% -14%`, coral `rgba(232,102,79,.22)` at `-4% 2%`, pink `rgba(224,83,127,.16)`
  at `50% 118%`.
- Eyebrow pill: "Private beta · invite only", 12px/600, `letter-spacing .08em`, uppercase,
  `#b8365f`, white 70% fill, border `rgba(224,83,127,.24)`, 6px `#e0537f` dot.
- H1: "Biotech screener that / finds binary events" (explicit `<br>`),
  `clamp(40px, 6.4vw, 74px)`, line-height 1.02, tracking `-.035em`, weight 600.
- Sub: max 620px, `clamp(17px, 2vw, 20px)`, line-height 1.5, `#6b6661`.
- Waitlist form (`#waitlist`, max 470px): pill row, 6px padding, white 78%, border
  `rgba(28,26,24,.1)`, shadow `0 10px 34px rgba(28,26,24,.07)`; borderless email input
  (placeholder `you@fund.com`), gradient submit "Request access".
- On submit: form is replaced by a pill reading "You're on the list. We'll email you when
  your seat opens." Microcopy under: "Free during the private beta. Not financial advice."
  13px `#8b8681`.

### 3. Product shot (`#product`, background `linear-gradient(#fbf8f5, #f4f0ec)`)
Browser-window frame: radius 20px, `#fdfbf9`, border `rgba(28,26,24,.08)`, shadow
`0 40px 90px -30px rgba(28,26,24,.28), 0 2px 8px rgba(28,26,24,.06)`; title bar with
11px traffic lights `#e8664f / #f4bd4c / #d9d4ce` and URL text "grapefruit.app / future
winners". Inside: app topbar, filter pills (search, `🌍 All countries`, `All catalysts`,
solid gold `⭐ Watchlist`), then a glass company card (radius 16px, `rgba(255,255,255,.55)`,
blur 20px, inset top highlight) containing:
- Inline SVG price chart, `viewBox 0 0 560 232`: coral `#e8664f` polyline (2px), axis lines
  `rgba(28,26,24,.25)`, catalyst window = gold `#f4bd4c` rect at 25% opacity bounded by two
  `#d79d00` 2px verticals. Chart data is illustrative (MAAT, ~$0–12, 2023-12 → 2026-02).
- Meta column: "MAAT — Maat Pharma SA 🇫🇷 ★(#f4bd4c)" 18px/700; sector 12px `#6b6661`;
  "$2.88 / $70M" 15px/600; past catalyst row with gold 3px left border; predicted catalyst
  row with blue `#2879d0` 3px left border; confidence `MEDIUM` in `#b27a00` 700.
- Catalyst timeline: 2px rail `rgba(107,102,97,.25)`, 10px dots (blue = predicted, `#d79d00`
  = past), 13.5px/700 rows, 20px circular `+` affordances; "Ask Perplexity" outline pill
  (`#e8664f` border, 10% coral fill).

### 4. Example (`#example`, background `#f4f0ec`)
Two-up `repeat(auto-fit, minmax(320px, 1fr))`, gap 56px, vertically centered.
- Left: eyebrow "One card, one thesis" (`#b8365f`), H2 "Every catalyst comes with its
  evidence attached", two 17px/1.55 `#6b6661` paragraphs.
- Right: glass card (radius 18px, white 72%) for **IVEVF — Inventiva S.A 🇺🇸**, `$3.59 /
  $848M`, with two `<details>` timeline rows that expand to full catalyst reasoning. The
  `+` glyph rotates 45° on open (`transition: transform .18s ease`). Past-catalyst row
  includes a "Was it foreseeable?" label and a green **Yes** chip
  (`rgba(31,138,76,.15)` / `#1f8a4c`, radius 4px).

### 5. Pricing (`#pricing`, background `#fbf8f5`)
Centered head + two cards, `minmax(260px, 1fr)`, max 760px, gap 20px. No free tier.
- **Operator €9 / month** — highlighted: white, border `rgba(224,83,127,.35)`, shadow
  `0 20px 50px -22px rgba(224,83,127,.4)`, overlapping "Most useful" badge
  (`linear-gradient(135deg, #e8664f, #e0537f)`, top `-11px`, left 26px). Features: full
  universe US + EU / forward catalyst scan 1–90 days / Ask Perplexity on any name /
  unlimited watchlist + email alerts. Gradient CTA.
- **Desk €29 / month** — plain white, border `rgba(28,26,24,.08)`. Features: everything in
  Operator / prediction hit-rate history / CSV + API access / three seats. Ghost CTA
  (border `rgba(28,26,24,.16)`, hover `rgba(28,26,24,.32)`).
- Price numerals 42px/600, tracking `-.03em`; `/ month` 14px `#8b8681`.

### 6. FAQ (`#faq`, background `#f4f0ec`)
Five `<details>` rows, max 780px, each `border-top: 1px rgba(28,26,24,.1)`, padding
`22px 4px` (last also has a bottom border). Summary 18px/500; `+` 22px `#b8365f`, rotates
45° when open. Answers 16px/1.6 `#6b6661`, `max-width: 62ch`. Questions: data sources /
refresh cadence / what counts as a past winner / survivorship bias / can I get in now.

### 7. Closing CTA + footer
- CTA band: pink + gold radials over `#fbf8f5`, H2 `clamp(30px, 4vw, 50px)` "Know what's on
  the calendar before the chart does", 16px gradient pill CTA.
- Footer: `#f4f0ec`, top border `rgba(28,26,24,.08)`, wordmark + links (Product / Pricing /
  FAQ / Contact `mailto:hello@grapefruit.app`), then the legal disclaimer at 12.5px/1.6
  `#7a746e`, max `78ch`, and `© 2026 Grapefruit`.

## Interactions & behavior
- Nav + CTAs are in-page anchors to `#product`, `#example`, `#pricing`, `#faq`, `#waitlist`.
- Waitlist form: HTML5 `type="email" required`; on submit prevent default, POST the email,
  swap the form for the confirmation pill. **Not yet wired** — the reference logs to
  console. Needs: a real endpoint, an error state (duplicate / invalid / network), and a
  disabled+"Sending…" button state while in flight.
- All `<details>` are native disclosure; only transition is the 45° `+` rotation, 180ms.
- Hover: nav color shift, CTA shadow lift, ghost-button border darkening. No scroll
  animations, no parallax, no autoplay — motion is deliberately minimal.
- Responsive: fluid throughout. Grids collapse via `auto-fit` at ~320px/260px track floors;
  type uses `clamp()`. Below ~720px the header nav will need a collapse treatment (not
  designed yet — simplest is hiding nav links and keeping the CTA).

## State management
Only one piece of state: `joined: boolean` (plus the controlled `email` string). No routing
state, no data fetching on this page.

## Design tokens
Colors
- Background warm: `#fbf8f5` (primary), `#f4f0ec` (alternate band), `#fdfbf9` (window fill)
- Ink: `#1c1a18` (headings/body), `#3a3733` (card body), `#6b6661` (secondary),
  `#7a746e` (legal), `#8b8681` (tertiary/placeholder)
- Brand gold `#f4bd4c`, deep gold `#d79d00`, amber text `#b27a00`
- Brand coral `#e8664f`; pink accent `#e0537f`, deep pink `#b8365f` (links/eyebrows)
- Data blue `#2879d0` (predicted catalyst); success green `#1f8a4c`
- Neutral chip `#d9d4ce`; hairlines `rgba(28,26,24,.06 / .08 / .1 / .16)`
- Signature gradients: CTA `linear-gradient(135deg, #e8664f, #f4bd4c)`; wordmark
  `linear-gradient(135deg, #f4bd4c, #e8664f 55%, #e0537f)`; badge
  `linear-gradient(135deg, #e8664f, #e0537f)`

Typography
- UI: system stack (`-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif`)
- Display: **Playfair Display** italic 500/600 — wordmark only (Google Fonts)
- Scale: H1 `clamp(40px,6.4vw,74px)`/1.02/`-.035em` · H2 `clamp(30px,3.6vw,44px)`/1.08/
  `-.03em` · closing H2 `clamp(30px,4vw,50px)` · lead `clamp(17px,2vw,20px)`/1.5 ·
  body 17px/1.55 · FAQ answer 16px/1.6 · card 13.5–15px · micro 12–13px
- Weights: 600 for all headings (never 700 at display size), 700 only inside cards

Spacing — 24px gutters; section padding 110px; hero 120/96; grid gaps 20 / 56px.
Radius — 999px (pills/buttons/inputs), 20px (window), 18px (cards), 16px (glass card), 4px (chip).
Shadows — CTA `0 6px 18px rgba(232,102,79,.28)` → hover `0 12px 28px rgba(232,102,79,.34)`;
window `0 40px 90px -30px rgba(28,26,24,.28), 0 2px 8px rgba(28,26,24,.06)`;
glass `0 8px 32px rgba(28,26,24,.1), inset 0 1px 0 rgba(255,255,255,.6)`;
highlighted price card `0 20px 50px -22px rgba(224,83,127,.4), 0 2px 10px rgba(28,26,24,.05)`.
Glass recipe — `rgba(255,255,255,.55–.78)` + `backdrop-filter: blur(20px) saturate(180%)`
+ `1px rgba(255,255,255,.6)` border (always ship the `-webkit-` prefix).

## Assets
- No raster images. 🍊 / 🇫🇷 / 🇺🇸 / ⭐ / 🌍 are system emoji — replace the logo emoji with a
  real mark before launch; it renders differently per OS.
- One hand-authored inline SVG chart with illustrative data. In the app this should come
  from the real `MiniChart` component.
- Playfair Display via Google Fonts `<link>`; self-host if the repo avoids third-party
  requests.
- Copy in the page is final-draft, written against README.md product claims.

## Before merging
1. Wire the waitlist endpoint + error/pending states.
2. Add `<meta property="og:*">` tags and a share image.
3. Mobile header nav treatment.
4. Replace the emoji logo with a real mark and a favicon.
5. Have the legal disclaimer reviewed — it is the page's regulatory surface.

## Files
- `index.html` — dependency-free static build of the page (this folder).
- `Grapefruit Landing.dc.html` — the original working design file (project root).
