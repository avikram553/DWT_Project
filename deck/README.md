# GeoCrash DE — Defense Deck

Imported from the Claude Design project *"Comprehensive project presentation outline"*
(`a201fef8-315f-4f48-a902-ccc9cf70c709`). 14 slides, 1920×1080, 10-minute oral defense.

## Present from this
- **`GeoCrash DE Defense Deck.html`** — self-contained standalone deck. Double-click → opens in any browser, works offline (only Google Fonts load over network). This is the file to present from.

### Navigation (inside the deck)
- `←` / `→`, `PgUp` / `PgDn`, `Space` — prev / next slide
- `Home` / `End` — first / last
- number keys — jump to slide
- `R` — reset to slide 1
- Speaker notes post to the parent window on nav (design-canvas viewer / PPTX export).

## Edit from this
`source/` holds the editable design-canvas source:

| File | Role |
| --- | --- |
| `GeoCrash Defense Deck.dc.html` | slide template — 14 inline-styled `<section>` slides, each with `data-speaker-notes` |
| `deck-stage.js` | reusable `<deck-stage>` web component — nav, scaling, speaker notes, print |
| `support.js` | design-canvas runtime that renders `<x-dc>` / `<x-import>` |
| `assets/germany-choropleth.png` | title-slide map (930×1150) |
| `assets/nearby-hazards-v2.png` | student-question screenshot (1692×1444) |
| `scratchpad.md` | outline + style notes (Spectral titles, Plex body/mono, `#ce3b33` accent) |

Edit slide markup in the `.dc.html`; assets are referenced relative (`assets/…`, `./deck-stage.js`). Re-export the standalone via the Claude Design project when done.

## Slide order
01 Title · 02 Agenda · 03 Motivation & Task · 04 Project Goals · 05 Data Sources ·
06 Design Decisions · 07 Database Design · 08 System Architecture · 09 API Design ·
10 Mandatory Questions · 11 Bonus (zero-accident municipalities) ·
12 Student Question (nearby hazards) · 13 Challenges · 14 Live Demo

See `../GeoCrashDE.md` for the full defense Q&A bank keyed to these slides.
