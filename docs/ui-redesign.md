# Dashboard UI redesign plan: legibility and organisation

Date: 2026-11-22. Status: proposal for review. Scope: `frontend/src` only (styles.css, App.tsx, components, pages) plus the Playwright test updates listed below. Not a rebrand: light theme, purple accent, Inter/Manrope stay.

Evidence reviewed: real-host screenshots (`%TEMP%\gs_bench\ui\desktop-*.png`, `phone-*.png`), mocked-suite screenshots (`frontend/test-results/screenshots/*.png`), all of `styles.css`, `App.tsx`, `pages/*`, `components/*`, and `tests/dashboard.spec.ts`.

## 1. Root causes (read first)

1. **`html{zoom:1.3}` (`--ui-zoom`) multiplies every CSS length by 1.3.** styles.css contains two generations of rules: the original ones written small to be zoomed (8–12px), and newer ones written as real sizes (13–14px). Both get ×1.3, so on screen a 10.4px uppercase label (`.field-label`, 8px) sits beside an 18.2px radio option (`.runtime-option`, 14px) under a 14.3px card title (`.profile-card-title strong`, 11px). That is the "too small relative to surrounding text" problem.
2. **The zoom also breaks phones.** `body{min-width:320px}` becomes 416 real px, so every phone page is wider than a 390px screen (phone screenshots are 416–692px wide; `phone-models.png` is 567, `phone-svc-omnivoice.png` 692).
3. **Grey text is pale.** `--muted:#85899a` is 3.48:1 on white and 3.21:1 on the page background, and about 40 hard-coded greys are lighter still (`#a4a6b2` 2.42:1, `#b3b5bf` 2.04:1, footer `#a5a7b1` 2.22:1). The microcopy also uses uppercase with wide letter-spacing (`letter-spacing:1.05px`), which makes small text harder to read.
4. **No tokens.** Colours and sizes are hard-coded in almost every rule, and some rules are duplicated with conflicting values (`.icon-button` at 25px with no border and again at 30px with a border; `.spin` and `@keyframes spin` twice; `.avatar` twice).

Decision: **remove the zoom** and write every size as a real size, using the tokens below. At desktop width the result looks about as large as today (the new scale is in rendered px), and the phone overflow goes away.

## 2. Tokens

Put all of these on `:root` at the top of styles.css. Every rule must use them: after this work, no rule may contain a hex colour or `font-size` value that is not a token (exceptions: media/crop overlays on dark video and the per-model palette from `modelColor()`).

### 2.1 Type scale (rendered px, root 16px; write as rem)

**Floor: 13px.** The only text allowed under 13px is the 12px bold numeric badge on file tiles (`.file-index`), which sits on a dark chip and holds one or two digits.

| Token | Size / line-height | Weight | Use |
| --- | --- | --- | --- |
| `--fs-display` | 30px / 1.15 (Manrope) | 700 | Big memory number (`.resource-value-row strong`) |
| `--fs-h1` | 28px / 1.2 (Manrope), 24px at ≤720px | 700 | Page title |
| `--fs-h2` | 20px / 1.3 (Manrope) | 700 | Section titles ("Recent results", "History", "Your recordings") |
| `--fs-h3` | 17px / 1.35 | 600 | Card titles (runtime name, resource card title, host name, modal title) |
| `--fs-stat` | 22px / 1.2 (Manrope) | 700 | Per-GPU value (`.gpu-value strong`) |
| `--fs-body` | 15px / 1.5 | 400 | Default UI text, inputs, options, descriptions, prompts |
| `--fs-input-touch` | 16px | 400 | Inputs/selects/textareas at ≤720px or `(pointer:coarse)`, so iOS does not zoom |
| `--fs-label` | 14px / 1.4 | 600 | Form labels, legends, nav items (15px for nav), buttons, tabs, table headers |
| `--fs-small` | 14px / 1.45 | 400 | Secondary text: help paragraphs, expected time, notes, fit rows |
| `--fs-meta` | 13px / 1.45 | 400 (600 for pills) | Metadata lines, captions, status pills, footer, tooltips on bars, legends |

Rules:
- **No uppercase micro-labels.** Drop `text-transform:uppercase`, all-caps literals, and `letter-spacing` > 0.01em on text under 17px. Labels are sentence case, 14px, weight 600, colour `--text-2`.
- In any group of neighbouring elements, the label is never smaller than 14px and never more than 2px smaller than the value it labels (e.g. label 14 / input 15; caption 13 / title 15).
- Line length for paragraphs: `max-width: 68ch`.

### 2.2 Colour tokens (contrast ratios measured with the WCAG 2.x formula)

Backgrounds: `--bg-page #f5f6f8` (unchanged), `--bg-surface #ffffff`, `--bg-sunken #f6f5fb` (writing guide, fit box, code), `--bg-accent-soft #efebff` (selected rows, active nav), `--bg-tabs #ecebf3`.

| Token | Hex | on surface #fff | on page #f5f6f8 | on sunken #f6f5fb | on accent-soft #efebff | Use |
| --- | --- | --- | --- | --- | --- | --- |
| `--text` | #1f2233 | 15.73 | 14.55 | 14.51 | 13.48 | Primary text, values, input text |
| `--text-2` | #454a5e | 8.77 | 8.11 | 8.09 | 7.52 | Labels, descriptions, inactive nav, secondary buttons |
| `--text-3` | #5d6275 | 6.05 | 5.60 | 5.58 | 5.19 | Lightest allowed text: metadata, captions, footer, placeholders' neighbours |
| `--placeholder` | #6e7387 | 4.70 | — | 4.34 (do not use) | — | Placeholder text (inputs are always white) |
| `--accent` | #5a3fd4 | 6.78 | 6.27 | 6.26 | 5.81 | Links, active nav/tab text, focus ring, primary button fill (white text 6.78) |
| `--accent-hover` | #4b32bd | 8.43 | 7.80 | 7.78 | 7.23 | Primary hover (white text 8.43) |
| `--success` | #1b7350 | 5.81 | 5.37 | 5.36 | 4.98 | "Running", "On", "Fits" |
| `--danger` | #b3303d | 6.16 | 5.70 | 5.69 | 5.28 | Errors, "Failed", short-of-memory, Delete (white on it 6.16) |
| `--warning` | #855400 | 6.43 | 5.95 | 5.93 | 5.51 | Stale, unknown, RAM-guard-off warning |
| `--info` | #1f5fb8 | 6.20 | 5.73 | 5.72 | 5.31 | Queued/running job status |
| `--border` | #dfe1e8 | 1.31 | — | — | — | Decorative card and divider lines only |
| `--border-strong` | #80869a | 3.62 | 3.35 | 3.34 | — | Input, select, textarea, checkbox and file-drop borders (≥3:1 UI boundary) |

Tinted status backgrounds (pill text on its own tint):

| Pair | Ratio |
| --- | --- |
| `--success` on `--success-soft #e8f6ee` | 5.21 |
| `--danger` on `--danger-soft #fdeeee` | 5.47 |
| `--warning` on `--warning-soft #fdf4e2` | 5.88 |
| `--info` on `--info-soft #e9f1fd` | 5.45 |
| `--text-2` on `--neutral-soft #f0f1f5` (Stopped pill) | 7.77 |
| `--accent` on `--bg-tabs` (active tab text if the tab were not white) | 5.73 |
| `--text-2` on `--bg-tabs` (inactive tab) | 7.41 |
| `#ffffff` on `--text` (tooltip) | 15.73 |
| Disabled button: `#4b4f63` on `#e4e1f5` | 6.31 |

Retired values and what they measured (all fail AA for their size):

| Current | Where | Ratio |
| --- | --- | --- |
| #85899a `--muted` | everywhere `var(--muted)` | 3.48 white / 3.21 page / 3.37 form |
| #a4a6b2 | `.nav-label`, `.micro-label` | 2.42 |
| #a2a5b3 | `.brand-lockup small` | 2.45 |
| #b3b5bf | `.version` | 2.04 |
| #9a9daa / #9a9ca9 | `.sidebar-footer p`, `.operation-copy small`, `.operation-empty`, `.worker-caption` | 2.70–2.73 |
| #9a9dab | `.breadcrumb` | 2.70 |
| #8b8e9d | `.topbar-right` | 3.25 |
| #8070d4 | `.eyebrow` on page | 3.74 |
| #9295a3 | `.page-heading p` on page | 2.75 |
| #898c9b | `.field-label`, `.field>span`, `.runtime-fit-head` | 3.24 on form bg |
| #999caa, #a1a3ae, #9b9daa | `.host-main small`, `.resource-value-row span`, `.resource-stats` | 2.51–2.73 |
| #a4a6b1, #b0b2bc | `.capacity-label`, `.gpu-name span` ("DEVICE 01") | 2.42, 2.11 |
| #a5a7b1 / #d3d4da | `.page-footer` / its `b` separator | 2.22 / 1.37 |
| #31b483, #9a9db0 | `.nav-state-on` ("ON"), `.nav-state` | 2.63, 2.68 |
| #878a99 on #fafafd | `.model-state` default (Stopped pill) | 3.29 |
| #a3843f, #2a8f69 | `.fit-unknown`, `.fit-yes` | 3.46, 3.92 |
| #3f81df | `.status-running` | 3.88 |
| #b6b8c2, #b1b4c0 | input placeholders | 1.98, 2.07 |
| #e5e6ec / #e7e8ee | `.text-input`, `.input-wrap` borders | 1.25 |
| #a7a4c2 | `.help-tip-button` "?" icon | 2.33 |
| #cfcbe6 | `.file-add` dashed border | 1.52 |
| white on ~#bdb0f4 | disabled primary (`opacity:.55`) e.g. "Make speech" | 1.97 |

`--purple:#7459e8` (white text 4.84) is replaced by `--accent` for fills and text. The brand mark and the memory-bar gradients may keep #7459e8 because they carry no text.

### 2.3 Spacing, radius, size

- Spacing scale: `--sp-1 4px`, `--sp-2 8px`, `--sp-3 12px`, `--sp-4 16px`, `--sp-5 20px`, `--sp-6 24px`, `--sp-8 32px`, `--sp-10 40px`. Card padding 20px (16px at ≤720px); gap between fields 20px; label-to-control 8px; gap between cards 16px.
- Radius: `--r-sm 6px` (pills, chips), `--r-md 8px` (inputs, buttons), `--r-lg 12px` (cards, rail, modal).
- Control heights: `--control-h 40px` (buttons, inputs, selects, tabs 36px), `--control-h-lg 44px` (Make button, Start/Stop). Under `(pointer:coarse)` every interactive control is at least 44×44px, including icon buttons, help "?" and remove-file buttons (enlarge the hit area with padding or a `::before` if the glyph stays small).
- Icons: lucide sizes are also ×1.3 today, so raise them when the zoom goes: nav 20, card/resource icons 20, buttons 16, inline-with-text 16, help "?" 18.
- Focus: a global `:focus-visible{outline:2px solid var(--accent);outline-offset:2px}`. Remove `outline:none` from `.text-input` and `.input-wrap input`, and give inputs `border-color:var(--accent); box-shadow:0 0 0 3px #5a3fd433` on focus. Every interactive element needs a visible focus style (nav links currently have none).

## 3. Problems found, by page (selector → issue → fix)

### Shell (App.tsx, all pages)

| Selector | Problem | Fix |
| --- | --- | --- |
| `html{zoom}`, `--ui-zoom`, `calc(100vh / var(--ui-zoom))` (body, `.app-shell`, `.main-content`, `.models-rail`, `.results-rail`) | Mixed scales, phone overflow | Remove the zoom; use `100dvh` |
| `.sidebar` `position:fixed; inset:0 auto 0 0` | In full-page screenshots the white panel stops at the viewport height (900px) and the page continues grey beside it. In a live browser the fixed panel fills the viewport, but the column is not part of the layout, and a tall nav relies on its own scroll | Make `.app-shell` a grid (`grid-template-columns: var(--sidebar-w) minmax(0,1fr)`). The `<aside>` becomes a grid item that stretches to the full page height and carries the white background and right border; an inner wrapper is `position:sticky; top:0; height:100dvh; overflow-y:auto`. Remove `margin-left` from `.main-content` |
| `.brand-lockup small` "LOCAL MODEL CONTROL" 8px caps, 2.45:1 | Faint | 13px `--text-3`, sentence case "Local model control" |
| `.nav-label` "WORKSPACE" 9px caps, 2.42:1 | Faint | Remove the "Workspace" heading (Overview/Connections need no heading) |
| `.nav-host-label` host name 9px caps, truncated ("DESKTOP (RTX 5090 + RTX 4…") | Faint, truncated | 14px/600 `--text-2`, sentence case, wraps to 2 lines (no ellipsis), status dot plus visually hidden status text |
| `.nav-item` 12px (15.6 rendered) `#7c8090` 3.93:1 | Below AA | 15px/500 `--text-2` |
| `.nav-state` "ON" 10px `#31b483` 2.63:1 | Faint; state shown by colour and caps | See §4 |
| `.nav-indicator` at `right:-16px` | Sits outside the item on the sidebar edge | 3px bar inside the item's left edge |
| `.sidebar-footer p` 10px 2.70:1, `.version` 8px 2.04:1 | Faint filler | Remove the paragraph (it repeats the page footer). Keep "Preview 0.2" at 13px `--text-3` |
| `.breadcrumb` 11px, `#9a9dab` 2.70:1 | Faint | 14px; host crumb `--text-3`, current page `--text` 600 |
| `.topbar-right` 10px 3.25:1 | Faint | 14px `--text-2` |
| `.eyebrow` 9px caps tracked, 3.74:1; host name upper-cased in `Service.tsx` (3 places) | Faint shouting | 14px/600 `--accent`, host name as written (drop `.toUpperCase()`) |
| `.page-heading p` 11px 2.75:1 | Faint | 16px `--text-2`, `max-width:68ch` |
| `.page-footer` 8px 2.22:1, separator 1.37:1 | Faint | 13px `--text-3`; separator `--text-3` |
| `.button` 10px, height 34 | Small | 14px/600, height 40px, padding 0 16px |
| `button:disabled{opacity:.55}` | White on washed purple 1.97:1 | Disabled primary: background #e4e1f5, text #4b4f63 (6.31:1); disabled secondary: background `--bg-page`, text `--text-3`, border `--border` |
| duplicate `.icon-button`, `.spin`, `.avatar` rules | Conflicting sizes | One definition each: icon button 40px (36px allowed in dense rows) with border `--border` |

### Overview (`pages/Overview.tsx`)

| Selector | Problem | Fix |
| --- | --- | --- |
| `.micro-label` HOST / ROLE / MEASUREMENT SCOPE 9px caps 2.42:1 | Faint | 13px `--text-3` sentence case |
| `.host-main strong` 12px; `.host-main small` 9px 2.73:1 | Value smaller than its page text | Host name `--fs-h3`; hostname/OS 14px `--text-3` |
| `.role-pill` 9px | Small | Status pill spec (§5.6) |
| `.host-updated` (only a green dot shows when live) | State by colour only | Dot plus text "Live" / "Updated 2 min ago" at 13px `--text-2` |
| `.service-tile` names (inherit 13px ×1.3 bold), status pill 8px, `small` workload | Long names wrap to 3 lines ("Qwen / Image / pictures") because the pill takes the right side; the pill text is tiny | Name 16px/600 on one line, wrapping to at most 2 lines; workload 13px `--text-3`; the pill moves under the name. Group the tiles by workload with the same groups and order as the sidebar (§4) |
| `.overview-recent` "RECENT RESULTS" micro-label; items: "cinematic · MiniMax H3 videos" | Faint heading; the titles say nothing useful | `h2` "Recent results"; each item a row with thumbnail (reuse `ResultThumb`), title 15px, model + time 13px `--text-3` |
| Resource cards: see Models | | |

### Connections (`pages/Connections.tsx`) and Test profiles (`components/Profiles.tsx`)

| Selector | Problem | Fix |
| --- | --- | --- |
| `.field>span` NAME / SERVER ADDRESS / ACCESS TOKEN 8px caps | Faint, tiny | 14px/600 `--text-2` sentence case ("Name", "Server address", "Access token") |
| `.field>small` 8px 2.6:1 | Faint | 13px `--text-3` |
| `.input-wrap` border 1.25:1, input 10px, placeholder 1.98:1 | Field boundary invisible | Border `--border-strong`, text 15px, placeholder `--placeholder` |
| `.profile-id` 8px, `.worker-caption` 8px, `.settings-note` 8px | Faint | 13px `--text-3`; settings note 14px `--text-2` |
| `.connection-copy strong/span` 10px, `.connection-scope` 9px | Small | 15px/600 `--text`, 14px `--text-2` |
| `.profile-data-grid span` 7px caps, `.profile-gpu-list` 7–8px, `.simulation-badge` 7px, `.profile-form-actions>span` 8px | Below 10px rendered | Labels 13px `--text-3`, values 15px, badge as a status pill |

### Models page (`ModelsPage` in `pages/Service.tsx`, `RuntimeCard` in `components/Runtime.tsx`, `components/Resources.tsx`)

| Selector | Problem | Fix |
| --- | --- | --- |
| `.profile-card-title strong` (runtime name) 11px vs `.runtime-option` 14px | Title smaller than its options (14.3 vs 18.2 rendered) | Title `--fs-h3`; options `--fs-body` |
| `.profile-id` "text · port 8160" 8px | Faint | 13px `--text-3` |
| `.runtime-description` 11px `#6d7080` with a 42px indent | Indent misaligned on phone | 15px `--text-2`, no indent at ≤720px |
| `.runtime-choice legend` MODEL / GPUS 11px caps | Caps | 14px/600 `--text-2` "Model", "GPUs" |
| `.runtime-body-split` (`1fr 280px`) inside a card already beside the 310px memory rail | At 1440 the controls column is about 165px wide: each GPU option wraps to 3 lines ("NVIDIA / GeForce / RTX 5090"), "Fits" overflows the fit box, and an empty History takes half the card | Split only when the card is wide: `container-type:inline-size` on `.runtime-card`, `@container (min-width: 760px)` for the two columns, stacked otherwise. History becomes a collapsed `<details>` titled "History (n)" when there are 0–2 entries. Options use the full row width and never wrap the GPU name |
| `.runtime-fit-head` "IF YOU START IT" 8px caps; `.runtime-fit-row small` 10px muted; `.fit-yes` 3.92:1, `.fit-unknown` 3.46:1 | Faint; verdict shown mostly by colour | Heading 14px/600 "If you start it". Each resource is a row of 3 cells (name 14px/600 · "needs 64 GiB, 87 GiB free after 4 GiB headroom" 14px `--text-2` · verdict). Verdicts are icon + word in `--success` / `--danger` / `--warning` |
| `.runtime-fit-note` 10px muted | Faint | 13px `--text-3` |
| `.worker-caption` "Stopped. Nothing is using memory." 8px | Smallest text next to the largest button | 14px `--text-2` |
| `.operation-copy strong/small` 9/8px; `.operation-empty` 9px | Faint | 14px/600 and 13px `--text-3` |
| `.runtime-settings` field labels (FieldLabel, 8px caps) | See forms | Form label spec |
| `.field-warning` `#9a6b00` | 4.69 OK but small | `--warning`, 14px, with AlertTriangle icon |
| Resource cards: `.resource-title h3` 11px, subtitle 9px, `.resource-value-row span` 10px 2.51:1, `.resource-stats` 9px 2.69:1, `.gpu-name span` "DEVICE 01" 7px 2.11:1, `.capacity-label` "MEASURED" 7px caps, `.sample-copy` 8px, `.resource-error` 8px | Smallest text on the site | Title `--fs-h3`; subtitle 13px `--text-3`; value `--fs-display` / `--fs-stat`; "of 126 GiB" 15px `--text-2`; Used/Available legend 13px `--text-2` with values 13px/600 `--text`; device id 13px `--text-3` ("Device 1"); capacity state as a status pill ("Measured", "Stale", "Partial", "No data"); errors 14px `--danger` |
| `.stats-dot` 5px; `.progress-track` #f0f1f5 (1.13:1 vs card) | Bar and legend hard to see | Track #e3e5ec; legend swatches 10px square |
| `.usage-seg[data-tip]::after` 9px; segments identified only by colour and hover | Small; hover-only | Tooltip 13px. Under each bar on the Models page add a legend: one row per running model (swatch, name, size) plus "Other programs"; segments stay focusable |
| `.icon-help` / `.icon-button` "?" on resource cards `#b4b6c0` | Faint | `--text-3`, 40px hit area |

### Generation pages (`ServicePage`, `GenerateForm`, `FilePicker`, `CropEditor`)

| Selector | Problem | Fix |
| --- | --- | --- |
| `.field-label` (FieldLabel, `label.toUpperCase()`) 8px caps, 3.24:1, "(OPTIONAL)" in caps | The main complaint: tiny faint labels above 15px inputs | 14px/600 `--text-2`, sentence case from the plugin's label; " (optional)" in 14px/400 `--text-3` |
| `.text-input` 10px, height 36, border 1.25:1, placeholder 2.07:1 | Faint | 15px (16px touch), height 40, `--border-strong`, `--placeholder`, white background |
| `.generate-form` (#fcfbff box with border) inside `.service-panel` card | Card inside a card; the double border adds noise and narrows the fields | Remove the inner box's border, background and padding; fields sit in the service card |
| `.service-status` 13px (16.9 rendered) next to an 8px pill | Status sentence too big, pill too small | Status sentence 15px `--text`, pill per §5.6, "Model settings" link 14px `--accent` |
| `.mode-tabs` / `.mode-tab` 10.5px; `.mode-help` 10.5px muted | Small; muted help 3.37:1 | Tabs 14px/600, height 36, inactive `--text-2` on `--bg-tabs`, active white + `--accent` + shadow; help 14px `--text-2`. On phone the tabs stay on one row and scroll horizontally if needed (currently "Describe a voice" drops to a second line inside the grey pill) |
| `.help-tip-button` 16px, icon 13px, #a7a4c2 2.33:1; `.help-tip-text` 9.5px | Faint target, small tooltip | Icon 18px `--text-3`, hover/expanded `--accent`, hit area 32px (44px touch); tooltip 14px/1.5 white on `--text`, max-width 320px |
| `.file-add` 10px, `small` 9px, dashed border 1.52:1 | Faint | 14px/600 `--accent`; "or drop it here" 13px `--text-3`; border 1.5px dashed `--border-strong` |
| `.file-tile figcaption` 9px; `.file-remove` 20px; `.file-index` 9.5px | Small target | Caption 13px; remove button 28px visual, 44px hit area on touch; index 12px/700 (the one exception) |
| `.framing>small` 9.5px, `.crop-zoom` 9.5px | Small | 13px `--text-3`; slider label 14px `--text-2` |
| `.field-guide summary` "Writing guide" 10px `#77718f` with default ▶ marker | Looks like an afterthought | 14px/600 `--accent` with a ChevronDown icon (rotates when open), remove the default marker; list 14px/1.55 `--text` on `--bg-sunken`, `max-width:68ch` |
| `.text-button` "More options" / "Advanced settings" 10px | Small | 14px/600 `--text-2`, chevron 16px, height 36 |
| `.generate-expected` 10px muted, 3.37:1 | The expected time is useful but faint | 14px `--text-2`, Clock icon 16px |
| Make button disabled (opacity) with no reason shown | "Make speech" looks broken | Disabled colours from §2.2, plus a 13px `--text-3` line beside the button naming what is missing (e.g. "Add what to say first") from the existing validity logic |
| `.field-problem` small | | 14px `--danger` with AlertCircle icon |

### Results rail and result modal (`ResultsRail`, `JobDetail`, `JobModal` in `Runtime.tsx`)

| Selector | Problem | Fix |
| --- | --- | --- |
| `.results-rail-head` 12px, count 10px muted | Small | `h2` 17px/600 "Your recordings"; count 13px `--text-3` ("4", or "1 composing · 1 queued") |
| `.result-text strong` 10.5px; `small` meta 9px muted 3.48:1, wraps to 3–4 lines ("Describe a voice · Female · Young adult · Any · British accent…") | Faint, long | Title 14px/600 clamped to 2 lines; status line 13px, colour plus icon (Loader2 running, Hourglass queued, AlertCircle failed, Ban cancelled); settings meta 13px `--text-3` clamped to 1 line with the full text in `title` (the modal shows it all); time on its own 13px line |
| `.status-running` `#3f81df` 3.88:1 | Below AA | `--info` |
| `.result-cancel` 26px | Small target | 36px (44px touch), `aria-label` unchanged |
| `.result-item-on` (selected) pale fill only | Weak | `--bg-accent-soft` plus a 3px `--accent` left bar |
| `.result-thumb` 112px | On phone it takes a third of the row and squeezes the text to 1–2 words per line | 112px desktop, 88px at ≤720px |
| `.job-modal-head strong` 12px; meta "Nov 22 · took 1 min 37 s" `small` 10px | Small | Title `--fs-h3`; meta 14px `--text-2` |
| `.job-section h4` 9px caps muted ("DESCRIPTION", "SETTINGS") | Faint caps | 15px/600 `--text`, sentence case |
| `.job-facts` 10.5px, `dt` muted | Small | 14px; `dt` `--text-3`, `dd` `--text` |
| `.job-prompt` 11px | Small | 15px/1.55 |
| `.job-sent summary` `#77718f` 10px, `pre` 10px | Small | Summary as writing-guide summary; `pre` 13px monospace |
| `.job-actions` buttons 10px 34px; Delete a plain secondary button | Small; destructive not distinct | 40px buttons. Delete: `--danger` text, border `--danger` at 40% alpha; confirm button solid `--danger` (white 6.16:1) |
| `.job-confirm` 10px | Small | 14px |
| `.job-modal` on phone | Fixed `94vw` | ≤720px: full screen (`100vw`×`100dvh`, radius 0); sticky header; close button 44px |

### Errors and refusals (`components/Refusal.tsx`, `.form-error`, `.inline-alert`, `.operation-error`)

| Selector | Problem | Fix |
| --- | --- | --- |
| `.refusal-details` code `strong` 9px tracked first, message 9px, `.refusal-resource` 8px | Code shown before the sentence; all tiny | Message first in 14px `--text` on `--danger-soft` with a 3px `--danger` left border and an AlertCircle icon; code after it in 13px monospace `--text-3`; resources as a 13px 3-column list (resource · Required · Available · Headroom). Keep the literal strings "Required 24 GiB", "Available 3 GiB", "Headroom 2 GiB" and the code text (tests match them) |
| `.form-error` 9px, `.inline-alert` 10px, `.operation-error` inherit small | Small | 14px `--danger` on `--danger-soft`, icon 16px |
| `.profile-gate`, `.runtime-fit-error`, `.stale-copy` (#ad8538 3.39:1) | Faint warning | 14px `--warning` on `--warning-soft` |

## 4. Sidebar: grouped by type

Structure for each host (`HostNav` in App.tsx):

```
Overview
Connections
─────────────
● Desktop (RTX 5090 + RTX 4080)      ← host heading, 14px/600, dot + hidden "Live"
  Models                    2 on      ← pill
  Speech                              ← group heading
    OmniVoice speech        ● On
    Qwen3-TTS speech        ● On
  Pictures
    Qwen Image pictures
  Video
    MiniMax H3 videos
  Music
    YuE2 songs
  Text                                ← only if a text runtime has `generation`
```

- Groups come from `runtime.workload` through one constant in App.tsx: `[['speech','Speech'],['image','Pictures'],['video','Video'],['music','Music'],['text','Text']]`. Unknown workloads go to "Other", last. Empty groups are not rendered. Items keep host order within a group. (This is the order the user named; it is one array, so it is easy to change.) Apply the same grouping and order to the Overview service tiles.
- Markup: each group is `<div role="group" aria-labelledby={id}>` with `<div className="nav-group-label" id={id}>Speech</div>` and the existing `NavLink`s. Links stay `<a>` with `aria-current="page"`.
- Group heading: 13px/600 `--text-3`, sentence case, 16px top margin, 4px bottom, aligned with the item text (not the icon).
- Item: height 40px, 15px/500 `--text-2`, icon 20px `--text-3`, radius 8. Hover background `--bg-page`. **Active**: background `--bg-accent-soft`, text and icon `--accent`, weight 600, 3px `--accent` bar on the inner left edge (5.81:1).
- **Running state**: replace the "ON" text with a pill: 8px `--success` dot + "On" in 13px/600 `--success` on `--success-soft` (5.21:1). Starting/stopping: a 14px `Loader2` spinner in `--text-3` plus visually hidden text "Starting"/"Stopping". Stopped after an error: an AlertCircle 14px `--danger` with hidden text "Error". Keep the `title` tooltip. Models link: "2 on" in the same pill. State is never colour alone (dot + word, or icon + hidden text).
- Desktop width `--sidebar-w: 264px` (≥1100px), 240px from 1100 to 1279px.
- **Icon rail (721–1099px)**: 72px wide, icons 22px, items 48px square. Groups separated by a 1px `--border` line with 8px margin (this separates the two identical speech icons). Running = 10px `--success` dot with a 2px white ring at the icon's top right; every link has a `title` and keeps its accessible name (name + state). The host heading becomes just the status dot with its accessible label.
- **Phone (≤720px)**: no rail. The topbar gets a 44px Menu button (lucide `Menu`, `aria-expanded`, `aria-controls="sidebar"`) at its left. The sidebar becomes a drawer, `min(320px, 86vw)` wide, sliding over a `#14162280` backdrop with the full grouped nav. It closes on Escape, on backdrop tap and on `hashchange`, and focus moves into it when it opens and returns to the button when it closes. Main content uses the full width. The `<nav aria-label="Main navigation">` element and its contents stay the same.

## 5. Component specs not covered above

1. **Cards** (`.profile-card`, `.resource-card`, `.host-strip`, `.results-rail`, `.service-panel`): white, 1px `--border`, radius 12, padding 20 (16 phone), shadow `0 1px 2px #15192b0d`. No cards inside cards.
2. **Page width**: `.page-wrap` padding 32px desktop, 24px tablet, 16px phone; max-width 1200 (service) / 1400 (models).
3. **Breakpoints** (after removing the zoom): ≥1280 full sidebar, results rail at the side (`minmax(0,1fr) 360px`, gap 24) and models memory rail at the side (320px). 1100–1279: sidebar 240, rails stacked above/below. 721–1099: icon rail, single column. ≤720: drawer, single column, inputs 16px, full-width Make button under the expected-time line. Use `minmax(0,1fr)` and `min-width:0` on every grid/flex child that holds text so long GPU names and prompts wrap instead of widening the page.
4. **Topbar**: height 64 (56 phone). At ≤720px only the Menu button, the current page title (15px/600, ellipsis) and the avatar show.
5. **Buttons**: primary `--accent`/white, hover `--accent-hover`; secondary white, border #c4c7d2 (1.7:1, acceptable because the button text identifies it), text `--text-2`, hover border `--accent` text `--accent`; danger as §3. Make/Start buttons 44px, 15px/600.
6. **Status pills** (`.model-state`, `.role-pill`, `.capacity-label`, `.simulation-badge`, nav "On"): 13px/600, sentence case, height 24px, padding 0 8px, radius 6, leading 14px icon: Running/Done/On/Measured `--success` on soft (CheckCircle2 or dot), Loading/Stopping/Queued/Running job `--info` (Loader2/Hourglass), Error/Failed `--danger` (AlertCircle), Stopped/Cancelled `--text-2` on `--neutral-soft` (CircleOff/Ban), Stale/Partial `--warning` (AlertTriangle).
7. **Disclosures** (`details` and toggle text-buttons): one style everywhere: 14px/600, ChevronDown 16px rotating 180° when open, 36px tall hit area.
8. **Motion**: keep the existing `prefers-reduced-motion` rule; the drawer transition must honour it.

## 6. Accessibility checklist (applies to every phase)

- All text ≥4.5:1 using only the tokens above; non-text boundaries for inputs, checkboxes and drop zones ≥3:1 (`--border-strong`).
- Visible `:focus-visible` ring on every link, button, tab, summary, slider, crop box and result row.
- Targets ≥40px on desktop, ≥44px under `(pointer:coarse)`.
- State never by colour alone: dots get words or hidden text; fit verdicts and job statuses get icons and words; selected rows get a bar as well as a tint.
- Keep accessible names and roles unchanged: `Main navigation`, `How to make it` tablist, `What {label} does` help buttons, `Cancel {title}`, `Add picture: {label}`, `Framing for/size for …` sliders, `Your {noun}s` complementary, `{noun}: {title}` article, form names "Make a song" etc., button texts "Start", "Stop", "Make a video", "Save and connect", "Load simulation", "Advanced settings".

## 7. Test impact (`frontend/tests/dashboard.spec.ts`)

- `getByLabel(/^STYLE/)`, `/^SHAPE/`, `/^CUSTOM WIDTH/`, `/^CUSTOM HEIGHT/`, `/^SEED/`, `/^RESOLUTION/`, `/^LYRICS/`, `/^DESCRIPTION/`, `/^WHAT HAPPENS/`, `/VRAM LEFT FREE ON THE MAIN CARD/`: regexes are case-sensitive, and labels become sentence case once `FieldLabel` stops calling `toUpperCase()`. Add the `i` flag (e.g. `/^style/i`). Do not use CSS `text-transform` as a workaround, because Chromium may expose the transformed text in the accessible name.
- `getByText('FIXTURE DESKTOP' | 'PROXMOX' | 'RECENT RESULTS' | 'STALE' | 'PARTIAL')`: Playwright string matching is case-insensitive and substring, so these still match sentence-case text. Check for new strict-mode ambiguity (e.g. "Stale" also inside "Telemetry stale"; the `STALE`/`PARTIAL` calls already use `.first()`). Prefer updating them to the new sentence-case text for clarity.
- `getByText('Running', { exact: true })` and `'Stopped'` exact: keep these pill texts exact (the icon is `aria-hidden`).
- Nav links' accessible names gain "On" (they already contained "on"); `getByRole('link', { name: /Models/ })` is unaffected.
- Screenshot files are regenerated by the suite. Add two to it: the grouped sidebar at 1440 and the open phone drawer at 390.

## 8. Phases

Do them in order. Each phase ends with `npm run build`, `npx playwright test`, the screenshots refreshed, and the acceptance checks below.

**Phase 1: remove the zoom, add tokens and the type scale.**
Remove `--ui-zoom`/`zoom` and every `/ var(--ui-zoom)`. Convert the remaining layout lengths ×1.3 (rounded; leave 1–2px borders and the 9999px crop shadow), then snap them to the spacing scale. Add all §2 tokens and replace every `font-size`, text colour, border colour and the button/input/pill base styles with tokens. Raise lucide icon sizes per §2.3. Delete duplicate rules. Global focus ring. Sentence-case `FieldLabel`, `.micro-label`, `.eyebrow`, field `span`s, capacity labels and pills (remove `.toUpperCase()` in Runtime.tsx line 36 and Service.tsx eyebrows, all-caps literals in Overview/Connections/Profiles/Resources/Runtime); update tests per §7.
Accept: `grep -E "font-size:(([0-9]|1[0-2])(\.[0-9]+)?px)" styles.css` finds only `.file-index`; no hex colours outside `:root` except media overlays; every page at 1440 looks the same size as before or larger; the phone screenshots at 390 are exactly 390px wide (no horizontal scroll on any page); axe or Lighthouse colour-contrast shows 0 failures on Overview, Models, a service page and the modal.

**Phase 2: shell and sidebar.**
Grid shell with sticky sidebar (fixes the short white panel); grouped nav (§4); new active and running indicators; topbar and footer restyle; icon rail separators and status dots.
Accept: the full-page desktop screenshot shows the white sidebar column to the bottom; groups appear in the order Speech, Pictures, Video, Music, Text, with empty groups hidden; with two speech models the rail shows them under one separator; running is readable without colour (the word "On"); keyboard Tab shows a focus ring on every nav link; tests pass.

**Phase 3: forms and the generation page.**
Flatten `.generate-form` into the service card; labels, inputs, tabs, help tips, file picker, framing, writing guide, disclosures, expected-time line, Make button with disabled reason.
Accept: on `make-a-song`, `video-from-pictures`, `framing` and `desktop-writing-guide`, no label is smaller than 14px, label/input sizes are 14/15, the help tooltip text is 14px, and drop zones and input borders are ≥3:1; the disabled Make button is legible and names what is missing.

**Phase 4: Models page, resource cards and Overview.**
Container-query split, option layout, fit table, history disclosure, resource card text, bar track and legend, status pills, host strip, Overview tiles grouped by workload, Recent results with thumbnails.
Accept: at 1440 GPU options are one line each and "Fits" stays inside its box; no Overview tile name wraps to 3 lines; "Device 1", "Measured", Used/Available are ≥13px and ≥4.5:1.

**Phase 5: results rail, modal, refusals and errors.**
Rail rows, statuses with icons, larger cancel buttons, selected bar; modal header, section headings, facts list, actions and danger styling; refusal and error blocks.
Accept: `song-queue`, `song-result`, `desktop-result-modal` and a refusal state (from the existing INSUFFICIENT_VRAM test) show no text under 13px; status is identifiable with colour removed (check a greyscale screenshot).

**Phase 6: phone.**
Drawer navigation with Menu button, phone topbar, 16px inputs, full-screen modal, 88px thumbnails, single-row scrolling tabs, full-width Make button.
Accept: at 390×844 every page is 390px wide; the drawer opens and closes with button, Escape, backdrop and navigation, and traps focus while open; touch targets ≥44px (Playwright with `hasTouch`); the results rail text uses at least half of the row width.

**Phase 7 (optional, later): dark mode.**
Worth adding only after the above, since the tokens make it a second set of values under `@media (prefers-color-scheme: dark)` plus a manual toggle saved in `localStorage`. Every pair must be re-measured to the same AA targets. The media areas (thumbnails, video, crop frame) are already dark and need no change. Not part of this revamp.
