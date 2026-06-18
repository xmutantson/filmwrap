# filmwrap

A small web app that prints wrap-around labels for 35mm film canisters.

I shoot a fair amount of expired film, and a 35mm cassette doesn't tell you when
it was bought or when it expires. I'd been handwriting those dates on the
canisters, so I made this to print tidy labels instead. Each label is a thin
strip: it prints the stuff I already know (film name, ISO, format, process,
purchase date, expiry) and leaves blank lines for the things I fill in later, the
event and the date I shot it. You cut a strip out, wrap it around the roll, and
tuck it into the canister tube.

It's a single `filmwrap.html` file. No install, no build, no server. Open it in a
browser and go. Your film library is saved locally in the browser, and you can
export/import it as JSON.

## Using it

1. Open `filmwrap.html` in your browser (double-click it).
2. Add your films: name, ISO, format, frames, process, purchase date, expiry,
   how many rolls, and a color. ("Load sample films" drops in a few examples.)
3. Tweak the strip size if you want, check the preview, and click Print sheet.
4. Cut along the guide lines, wrap a strip around each roll, and put it in the tube.
   Write the event and date after you've shot it.

### Print settings

In the browser print dialog, set **Margins: None** and turn on **Print
backgrounds** (otherwise the color accent bars don't print). Scale can be 100% or
"Fit to page width"; both come out at the right physical size, since the sheet is
laid out in real inches.

## Features

- Film library with add / duplicate / delete. Each film tracks brand, ISO, format,
  frame count, process (C-41 / E-6 / B&W), purchase date, expiry, roll count, and a
  color accent for sorting at a glance.
- Strips auto-stretch to the page width by default; turn that off for a fixed length,
  or use the wrap calculator (canister diameter x wraps).
- Cut-line grid so you can cut straight lines.
- Live preview with zoom, Letter or A4, adjustable margin / strip height / gap /
  font / text size, and toggles for which fields print.
- Saves to the browser automatically, with JSON export/import for backups or moving
  between machines.

## Privacy

It runs entirely offline and makes no network requests. The library lives in your
browser's `localStorage`. Export gives you a JSON backup; import restores it or
copies it to another browser.

## Tests

It's plain HTML/CSS/JS in one file, so just edit `filmwrap.html`. There's a
Playwright suite (`test_filmwrap.py`) that drives the page in headless Chromium and
checks the behavior, including generating a print PDF and asserting it's 3 pages of
8.5x11in with no blank pages.

```bash
pip install playwright pypdf
playwright install chromium
python test_filmwrap.py
```

## License

[MIT](LICENSE), Copyright 2026 Kameron Markham.
