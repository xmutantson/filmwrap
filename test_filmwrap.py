"""
Functional tests for filmwrap.html. Drives the real page in headless Chromium.
Run: python test_filmwrap.py   (pip install playwright pypdf; playwright install chromium)
"""
import json, tempfile, os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HTML = Path(__file__).with_name("filmwrap.html").resolve()
URL = HTML.as_uri()

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))

def approx(a, b, tol=0.06):
    return abs(a - b) <= tol * max(abs(b), 1e-9)

def pdf_page_count(pdf_bytes):
    try:
        import pypdf
        from io import BytesIO
        return len(pypdf.PdfReader(BytesIO(pdf_bytes)).pages)
    except Exception:
        import re
        counts = [int(m) for m in re.findall(rb'/Count\s+(\d+)', pdf_bytes)]
        return max(counts) if counts else -1

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()

    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append("pageerror: " + str(e)))

    page.goto(URL)
    page.wait_for_selector("#films", state="attached")

    # 1. Boots without JS errors
    check("boot: no console/page errors", len(console_errors) == 0, str(console_errors))

    # 2. Starts EMPTY
    n_cards = page.eval_on_selector_all(".film", "els => els.length")
    has_empty_note = page.query_selector(".empty-note") is not None
    summary = page.inner_text("#summary")
    check("start empty: 0 film cards", n_cards == 0, f"cards={n_cards}")
    check("start empty: empty-note shown", has_empty_note)
    check("start empty: summary says 0 films", "0 film" in summary, summary)

    # 3. Load sample films
    page.click("#loadSamples")
    page.wait_for_selector(".film")
    n_cards = page.eval_on_selector_all(".film", "els => els.length")
    n_sheets = page.eval_on_selector_all(".sheet", "els => els.length")
    check("load samples: 4 film cards", n_cards == 4, f"cards={n_cards}")
    check("load samples: at least 1 sheet rendered", n_sheets >= 1, f"sheets={n_sheets}")
    n_strips = page.eval_on_selector_all(".strip", "els => els.length")
    # samples qty: 5+8+4+6 = 23
    check("load samples: 23 strips (5+8+4+6)", n_strips == 23, f"strips={n_strips}")

    # 4. ZOOM: measure a sheet's rendered width at two zoom levels.
    zoom_val_before = page.eval_on_selector("#zoom", "el => el.value")
    w1 = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().width")
    page.eval_on_selector("#zoom",
        "el => { el.value='1.2'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(80)
    w2 = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().width")
    zoomval_text = page.inner_text("#zoomval")
    ratio = (w2 / w1) if w1 else 0
    expected = 1.2 / float(zoom_val_before or 0.7)
    check("zoom: slider initialised to a value", zoom_val_before not in (None, ""), f"value={zoom_val_before}")
    check("zoom: sheet grows when slider moved 0.7->1.2",
          ratio > 1.3 and approx(ratio, expected, 0.08),
          f"w1={w1:.1f} w2={w2:.1f} ratio={ratio:.3f} expected~{expected:.3f}")
    check("zoom: %% readout updates to 120%", zoomval_text.strip() == "120%", f"zoomval='{zoomval_text}'")
    # restore
    page.eval_on_selector("#zoom",
        "el => { el.value='0.7'; el.dispatchEvent(new Event('input',{bubbles:true})); }")

    # 5. Quantity change updates strip count
    page.eval_on_selector('.film input[data-k="qty"]',
        "el => { el.value='10'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(50)
    n_strips2 = page.eval_on_selector_all(".strip", "els => els.length")
    check("qty edit: strip count changes (5->10 = +5 => 28)", n_strips2 == 28, f"strips={n_strips2}")

    # 6. Add / duplicate / delete
    page.click("#addFilm")
    page.wait_for_timeout(30)
    check("add film: 5 cards", page.eval_on_selector_all(".film", "e=>e.length") == 5)
    page.eval_on_selector_all('[data-dup]', "els => els[0].click()")
    page.wait_for_timeout(30)
    check("duplicate: 6 cards", page.eval_on_selector_all(".film", "e=>e.length") == 6)
    page.eval_on_selector_all('[data-del]', "els => els[els.length-1].click()")
    page.wait_for_timeout(30)
    check("delete: back to 5 cards", page.eval_on_selector_all(".film", "e=>e.length") == 5)

    # 7. Settings toggles affect the rendered strips
    page.eval_on_selector('[data-set="showCut"]',
        "el => { if(el.checked){el.checked=false; el.dispatchEvent(new Event('input',{bubbles:true}));} }")
    page.wait_for_timeout(40)
    has_nocut = page.eval_on_selector(".grid", "el => el.classList.contains('nocut')")
    check("toggle cut lines off: grid gets .nocut", has_nocut is True)

    page.eval_on_selector('[data-set="accent"]',
        "el => { if(el.checked){el.checked=false; el.dispatchEvent(new Event('input',{bubbles:true}));} }")
    page.wait_for_timeout(40)
    n_accent = page.eval_on_selector_all(".strip .accent", "els => els.length")
    check("toggle accent off: no .accent bars", n_accent == 0, f"accent els={n_accent}")
    # turn accent back on
    page.eval_on_selector('[data-set="accent"]',
        "el => { el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); }")

    # 7b. Full-width toggle (ON by default): strip auto-spans the page; length field locks
    fw_default = page.eval_on_selector('[data-set="fullWidth"]', "el => el.checked")
    sw = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().width")
    st = page.eval_on_selector(".strip", "el => el.getBoundingClientRect().width")
    disabled_default = page.eval_on_selector("#stripLen", "el => el.disabled")
    lenval = page.eval_on_selector("#stripLen", "el => el.value")
    check("full-width: ON by default", fw_default is True)
    check("full-width default: strip spans the full sheet width", approx(st / sw, 1.0, 0.02), f"ratio={st/sw:.3f}")
    check("full-width default: length field locked", disabled_default is True)
    check("full-width default: length auto = ~8.5in", approx(float(lenval), 8.5, 0.03), f"len={lenval}")
    # toggle OFF -> field re-enabled, strip falls back to the narrower manual length
    page.eval_on_selector('[data-set="fullWidth"]',
        "el => { el.checked=false; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    st2 = page.eval_on_selector(".strip", "el => el.getBoundingClientRect().width")
    reenabled = page.eval_on_selector("#stripLen", "el => !el.disabled")
    check("full-width OFF: length field re-enabled", reenabled is True)
    check("full-width OFF: strip narrower than sheet", st2 / sw < 0.95, f"ratio={st2/sw:.3f}")

    # 7c. Margin insets content within a FULL-PAGE sheet (so "Fit to page width" can't erase it)
    page.eval_on_selector('[data-set="fullWidth"]', "el => { el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.eval_on_selector('[data-set="margin"]', "el => { el.value='0'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    sheet_w_m0 = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().width")
    page.eval_on_selector('[data-set="margin"]', "el => { el.value='0.15'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    sheet_w_m15 = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().width")
    strip_w_m15 = page.eval_on_selector(".strip", "el => el.getBoundingClientRect().width")
    check("margin: sheet stays full page width regardless of margin (fit-to-width safe)",
          approx(sheet_w_m0, sheet_w_m15, 0.01), f"m0={sheet_w_m0:.1f} m15={sheet_w_m15:.1f}")
    check("margin 0.15: full-width strip insets to ~8.2/8.5 of the sheet",
          approx(strip_w_m15 / sheet_w_m15, 8.2 / 8.5, 0.02), f"ratio={strip_w_m15/sheet_w_m15:.3f}")
    # reset for following tests
    page.eval_on_selector('[data-set="margin"]', "el => { el.value='0'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.eval_on_selector('[data-set="fullWidth"]', "el => { el.checked=false; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(30)

    # 8. Overflow warning when strip longer than the page (full-width is OFF here)
    page.eval_on_selector('[data-set="stripLen"]',
        "el => { el.value='12'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    hint_html = page.inner_html("#wrapHint")
    check("overflow: warning shown for 12in strip", "exceeds" in hint_html and "danger" in hint_html, hint_html[:120])
    page.eval_on_selector('[data-set="stripLen"]',
        "el => { el.value='7.5'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    hint_html2 = page.inner_html("#wrapHint")
    check("overflow: warning clears at 7.5in", "exceeds" not in hint_html2, hint_html2[:120])

    # 9. Font-size scale changes strip font-size
    fs1 = page.eval_on_selector(".ident .fname", "el => parseFloat(getComputedStyle(el).fontSize)")
    page.eval_on_selector('[data-set="fscale"]',
        "el => { el.value='1.4'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    fs2 = page.eval_on_selector(".ident .fname", "el => parseFloat(getComputedStyle(el).fontSize)")
    check("fscale: font grows at 1.4x", fs2 > fs1 + 1, f"{fs1:.1f}->{fs2:.1f}")
    page.eval_on_selector('[data-set="fscale"]',
        "el => { el.value='1'; el.dispatchEvent(new Event('input',{bubbles:true})); }")

    # 10. Print media: chrome hidden, sheets-wrap zoom reset, accent set to exact color-adjust
    page.emulate_media(media="print")
    panel_disp = page.eval_on_selector(".panel", "el => getComputedStyle(el).display")
    tb_disp = page.eval_on_selector(".toolbar", "el => getComputedStyle(el).display")
    accent_adjust = page.eval_on_selector(".strip .accent",
        "el => getComputedStyle(el).printColorAdjust || getComputedStyle(el).webkitPrintColorAdjust")
    check("print: control panel hidden", panel_disp == "none", panel_disp)
    check("print: toolbar hidden", tb_disp == "none", tb_disp)
    check("print: accent has print-color-adjust:exact", accent_adjust == "exact", str(accent_adjust))
    page.emulate_media(media="screen")

    # 11. Clear all (handle confirm dialog)
    page.on("dialog", lambda d: d.accept())
    page.click("#clearFilms")
    page.wait_for_timeout(60)
    check("clear all: 0 cards + empty note",
          page.eval_on_selector_all(".film", "e=>e.length") == 0 and page.query_selector(".empty-note") is not None)

    # 12. Persistence across reload (same context keeps localStorage)
    page.click("#loadSamples")
    page.wait_for_timeout(40)
    page.reload()
    page.wait_for_selector("#films", state="attached")
    persisted = page.eval_on_selector_all(".film", "e=>e.length")
    check("persistence: samples survive reload", persisted == 4, f"cards={persisted}")

    # 13. Fresh context (new browser profile) starts empty -> proves no hardcoded preload
    ctx2 = browser.new_context()
    page2 = ctx2.new_page()
    page2.goto(URL)
    page2.wait_for_selector("#films", state="attached")
    fresh_cards = page2.eval_on_selector_all(".film", "e=>e.length")
    check("fresh browser: starts empty", fresh_cards == 0, f"cards={fresh_cards}")
    fresh_margin = page2.eval_on_selector('[data-set="margin"]', "el => el.value")
    check("fresh browser: default margin is 0", fresh_margin == "0", f"margin={fresh_margin}")
    cy = page2.inner_text("#copyYear")
    cy_expected = str(page2.evaluate("() => new Date().getFullYear()"))
    check("copyright: year shown matches current year", cy == cy_expected and cy.isdigit(),
          f"shown={cy} expected={cy_expected}")
    check("copyright: Kameron Markham credit present", "Kameron Markham" in page2.inner_text(".panel"))

    # 14. Import roundtrip via the hidden file input
    lib = {"films": [{"name": "TEST FILM XYZ", "iso": "100", "format": "35mm", "frames": "36",
                      "process": "C-41", "purchase": "2025-05-01", "expiry": "2028-04", "qty": 3,
                      "color": "#ff0000"}],
           "settings": {}}
    tmp = os.path.join(tempfile.gettempdir(), "filmwrap_test_lib.json")
    Path(tmp).write_text(json.dumps(lib), encoding="utf-8")
    page2.set_input_files("#importFile", tmp)
    page2.wait_for_function("() => document.querySelectorAll('.film').length === 1")
    name_val = page2.eval_on_selector('.film input[data-k="name"]', "el => el.value")
    strip_cnt = page2.eval_on_selector_all(".strip", "els => els.length")
    check("import: film loaded from JSON", name_val == "TEST FILM XYZ", name_val)
    check("import: qty 3 -> 3 strips", strip_cnt == 3, f"strips={strip_cnt}")

    # 15. Import hardening: malformed (films not an array) is rejected, no crash
    page2.on("dialog", lambda d: d.accept())
    bad = os.path.join(tempfile.gettempdir(), "filmwrap_bad.json")
    Path(bad).write_text('{"films": {"not":"an array"}}', encoding="utf-8")
    errs_before = len(console_errors)
    page2.set_input_files("#importFile", bad)
    page2.wait_for_timeout(120)
    still_one = page2.eval_on_selector_all(".film", "e=>e.length")
    check("import hardening: bad file rejected, state intact",
          still_one == 1, f"cards={still_one}")

    # 16. Export produces a download with the right name + valid JSON
    with page2.expect_download() as dl:
        page2.click("#exportBtn")
    download = dl.value
    dlpath = download.path()
    data = json.loads(Path(dlpath).read_text(encoding="utf-8"))
    check("export: filename filmwrap-library.json", download.suggested_filename == "filmwrap-library.json",
          download.suggested_filename)
    check("export: JSON has films+settings", "films" in data and "settings" in data)

    # 17. Real print PDF at margin 0, on an isolated clean page:
    #     exact Letter sizing, no blank pages. Directly answers "letter size isn't exact".
    import pypdf
    from io import BytesIO
    ctx3 = browser.new_context()
    page3 = ctx3.new_page()
    page3.goto(URL)
    page3.wait_for_selector("#films", state="attached")
    page3.click("#loadSamples")
    page3.wait_for_selector(".film")
    dom_sheets = page3.eval_on_selector_all(".sheet", "e=>e.length")
    app_margin = page3.eval_on_selector('[data-set="margin"]', "el => el.value")
    rdr = pypdf.PdfReader(BytesIO(page3.pdf(prefer_css_page_size=True, print_background=True)))
    pdf_pages = len(rdr.pages)
    boxes = set((round(float(p.mediabox.width) / 72, 2), round(float(p.mediabox.height) / 72, 2))
                for p in rdr.pages)
    check("print PDF: app margin is 0", app_margin == "0", f"margin={app_margin}")
    check("print PDF: page count == on-screen sheets (no blank pages)",
          pdf_pages == dom_sheets, f"dom_sheets={dom_sheets} pdf_pages={pdf_pages}")
    check("print PDF: every page is exactly 8.5x11in (Letter)",
          boxes == {(8.5, 11.0)}, f"boxes={boxes}")

    browser.close()

print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"RESULT: {passed}/{total} passed")
fails = [(n, d) for n, ok, d in results if not ok]
if fails:
    print("FAILURES:")
    for n, d in fails:
        print(f"  - {n}: {d}")
raise SystemExit(0 if passed == total else 1)
