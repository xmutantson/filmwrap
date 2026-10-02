"""
Functional tests for filmwrap.html. Drives the real page in headless Chromium.
Run: python test_filmwrap.py   (pip install -r requirements-dev.txt; playwright install chromium)
"""
import json, sys
from io import BytesIO
from pathlib import Path
import pypdf
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

console_errors = []
network_requests = []

def new_page(browser):
    """Every scenario uses an ephemeral profile and blocks external requests."""
    ctx = browser.new_context()
    def offline(route):
        if route.request.url.startswith(("http:", "https:")):
            network_requests.append(route.request.url)
            route.abort()
        else:
            route.continue_()
    ctx.route("**/*", offline)
    page = ctx.new_page()
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append("pageerror: " + str(e)))
    return page

def upload(page, data):
    # In-memory files cannot collide with another process's temporary files.
    with page.expect_event("dialog"):
        page.set_input_files("#importFile", {
            "name": "test-library.json", "mimeType": "application/json",
            "buffer": json.dumps(data).encode("utf-8"),
        })

def stored(page):
    return page.evaluate("JSON.parse(localStorage.getItem('filmwrap.v1'))")

def set_setting(page, key, value):
    el = page.locator(f'[data-set="{key}"]')
    kind = el.get_attribute("type")
    if kind == "checkbox":
        el.set_checked(value)
    elif el.evaluate("el => el.tagName") == "SELECT":
        el.select_option(value)
    else:
        el.fill(str(value))
        el.dispatch_event("change")

def run_reliability_checks(browser):
    page = new_page(browser)
    page.goto(URL)
    page.click("#loadSamples")
    before = stored(page)
    page.evaluate("""() => {
        window.originalSetItem = Storage.prototype.setItem;
        Storage.prototype.setItem = function(){ throw new Error('Storage unavailable'); };
    }""")
    page.locator('[data-k="name"]').first.fill("Unsaved film")
    check("save failure: visible warning and existing save unchanged",
          "Changes are not saved" in page.inner_text("#saveStatus") and stored(page) == before)
    with page.expect_download() as dl:
        page.click("#exportBtn")
    exported = json.loads(Path(dl.value.path()).read_text(encoding="utf-8"))
    check("save failure: export retains current work", exported["films"][0]["name"] == "Unsaved film")
    page.evaluate("() => { Storage.prototype.setItem = window.originalSetItem; }")
    page.locator('[data-k="name"]').first.fill("Saved film")
    check("storage recovery: next edit saves and clears warning",
          page.locator("#saveStatus").get_attribute("data-status") == "saved"
          and stored(page)["films"][0]["name"] == "Saved film")

    before = stored(page)
    page.locator("[data-del]").first.click()
    page.click("#undoBtn")
    check("delete: undo restores and saves the whole library", stored(page) == before)
    accept = [False]
    page.on("dialog", lambda d: d.accept() if accept[0] else d.dismiss())
    replacement = {"films": [{"name": "Imported film", "qty": 2}], "settings": {"paper": "a4"}}
    upload(page, replacement)
    check("import: cancel leaves saved library unchanged", stored(page) == before)
    accept[0] = True
    upload(page, replacement)
    page.wait_for_function("document.querySelectorAll('.film').length === 1")
    check("import: confirmation replaces films and settings",
          stored(page)["films"][0]["name"] == "Imported film" and stored(page)["settings"]["paper"] == "a4")
    page.click("#undoBtn")
    check("import: undo restores previous films and settings", stored(page) == before)
    page.click("#clearFilms")
    page.click("#undoBtn")
    check("clear: undo restores the library", stored(page) == before)
    page.locator("[data-del]").first.click()
    page.locator('[data-k="name"]').first.fill("Later edit")
    check("undo: later edit dismisses stale recovery", page.locator("#undoRow").is_hidden())

    page.evaluate("window.firstSheet = document.querySelector('.sheet')")
    page.locator("#zoom").evaluate("el => { el.value='1'; el.dispatchEvent(new Event('input')); }")
    check("zoom: existing sheet DOM is preserved", page.evaluate("window.firstSheet === document.querySelector('.sheet')"))
    page.locator("#stripH").fill("0.2")
    page.locator("#stripH").press("Tab")
    height = page.locator("#stripH").input_value()
    check("geometry: control, preview and save use the same minimum height",
          height == "0.25" and stored(page)["settings"]["stripH"] == 0.25
          and page.locator(".grid").first.evaluate("el => el.style.gridAutoRows") == "0.25in")
    page.reload()
    check("geometry: accepted height is stable after reload", page.locator("#stripH").input_value() == height)
    page.locator("#stripH").fill("")
    page.locator("#stripH").press("Tab")
    check("geometry: blank draft restores last valid value", page.locator("#stripH").input_value() == height)
    page.click("#clearFilms")
    set_setting(page, "paper", "a4")
    set_setting(page, "margin", 0.2)
    check("empty library: wrap hint follows paper and margin",
          "full width 7.87in" in page.inner_text("#wrapHint"))
    page.context.close()

    # A malformed save is recoverable and cannot be overwritten by ordinary edits.
    page = new_page(browser)
    page.goto(URL)
    raw = json.dumps({"settings": {"paper": "a4"}})  # missing the required films list
    page.evaluate("raw => localStorage.setItem('filmwrap.v1', raw)", raw)
    page.reload()
    check("saved shape: invalid library boots empty with recovery notice",
          page.locator(".film").count() == 0 and page.locator("#savedRecovery").is_visible())
    page.click("#addFilm")
    check("saved shape: editing preserves unreadable original",
          page.evaluate("localStorage.getItem('filmwrap.v1')") == raw)
    with page.expect_download() as dl:
        page.click("#downloadSaved")
    check("saved shape: original data can be downloaded unchanged",
          Path(dl.value.path()).read_text(encoding="utf-8") == raw)
    page.on("dialog", lambda d: d.accept())
    page.evaluate("""() => {
        window.originalSetItem = Storage.prototype.setItem;
        Storage.prototype.setItem = function(){ throw new Error('Storage unavailable'); };
    }""")
    page.click("#replaceSaved")
    check("recovery: failed replacement preserves original and recovery controls",
          page.evaluate("localStorage.getItem('filmwrap.v1')") == raw
          and page.locator("#savedRecovery").is_visible())
    page.evaluate("() => { Storage.prototype.setItem = window.originalSetItem; }")
    page.click("#replaceSaved")
    check("recovery: explicit replacement saves current library",
          len(stored(page)["films"]) == 1 and page.locator("#savedRecovery").is_hidden())
    page.context.close()

    # A read failure must not become an automatic overwrite when writing still works.
    page = new_page(browser)
    page.goto(URL)
    page.click("#loadSamples")
    before = stored(page)
    page.add_init_script("""
        window.originalGetItem = Storage.prototype.getItem;
        Storage.prototype.getItem = function(){ throw new Error('Storage unreadable'); };
    """)
    page.reload()
    page.click("#addFilm")
    original = page.evaluate("JSON.parse(window.originalGetItem.call(localStorage, 'filmwrap.v1'))")
    check("storage read failure: original remains protected from edits",
          original == before and page.locator("#savedRecovery").is_visible()
          and page.locator("#downloadSaved").is_hidden())
    page.context.close()

    page = new_page(browser)
    page.goto(URL)
    page.evaluate("""() => localStorage.setItem('filmtube.v2', JSON.stringify({
        films:[{name:'Legacy film',qty:2}],settings:{paper:'a4'}
    }))""")
    page.reload()
    check("legacy: earlier library still loads", page.locator('[data-k="name"]').input_value() == "Legacy film")
    page.locator('[data-k="name"]').fill("Migrated film")
    check("legacy: next edit writes current key", stored(page)["films"][0]["name"] == "Migrated film")
    page.context.close()

def run_review_regressions(browser):
    page = new_page(browser)
    page.goto(URL)
    page.click('#addFilm')
    page.locator('[data-k="name"]').fill('Original')
    other = page.context.new_page()
    other.goto(URL)
    page.locator('[data-k="name"]').fill('Latest saved name')
    other.wait_for_function("document.querySelector('#saveStatus').textContent.includes('Save conflict')")
    check('tabs: external save invalidates stale Saved status',
          other.locator('#saveStatus').get_attribute('data-status') == 'error')
    other.locator('[data-k="qty"]').fill('2')
    check('tabs: stale edit preserves latest save and reports conflict',
          stored(other)['films'][0]['name'] == 'Latest saved name'
          and stored(other)['films'][0]['qty'] == 1
          and 'Save conflict' in other.inner_text('#saveStatus'))
    with other.expect_download() as dl:
        other.click('#exportBtn')
    exported = json.loads(Path(dl.value.path()).read_text(encoding='utf-8'))
    check('tabs: stale tab can export its unsaved work',
          exported['films'][0]['name'] == 'Original' and exported['films'][0]['qty'] == 2)
    before = stored(other)
    other.locator('[data-del]').click()
    other.click('#undoBtn')
    check('tabs: delete and undo cannot bypass conflict', stored(other) == before)
    other.on('dialog', lambda d: d.accept())
    upload(other, {'films': [{'name': 'Imported conflict', 'qty': 1}]})
    other.wait_for_function("document.querySelector('[data-k=name]').value === 'Imported conflict'")
    check('tabs: import cannot bypass conflict', stored(other) == before)
    other.reload()
    other.locator('[data-k="qty"]').fill('3')
    check('tabs: reload adopts latest library and allows saving',
          stored(other)['films'][0]['name'] == 'Latest saved name'
          and stored(other)['films'][0]['qty'] == 3
          and other.locator('#saveStatus').get_attribute('data-status') == 'saved')
    page.context.close()

    # Same-document mutations do not dispatch storage events: the save itself
    # must detect changes, removals and clear(), even without event delivery.
    for operation in ('update', 'remove', 'clear'):
        page = new_page(browser)
        page.goto(URL)
        page.click('#addFilm')
        page.evaluate("""operation => {
            if(operation==='clear') localStorage.clear();
            else if(operation==='remove') localStorage.removeItem('filmwrap.v1');
            else {
                const next=JSON.parse(localStorage.getItem('filmwrap.v1'));
                next.films[0].name='External save';
                localStorage.setItem('filmwrap.v1',JSON.stringify(next));
            }
        }""", operation)
        before = page.evaluate("localStorage.getItem('filmwrap.v1')")
        page.locator('[data-k="name"]').fill('Stale edit')
        check(f'tabs: {operation} detected before write without storage event',
              page.evaluate("localStorage.getItem('filmwrap.v1')") == before
              and 'Save conflict' in page.inner_text('#saveStatus'))
        page.context.close()

    for raw, recovery in (('{corrupt', True),
                          (json.dumps({'films': [{'name': 'Legacy', 'qty': 1}]}), False)):
        page = new_page(browser)
        page.goto(URL)
        page.evaluate("raw=>localStorage.setItem('filmtube.v2',raw)", raw)
        page.reload()
        other = page.context.new_page()
        other.goto(URL)
        if recovery:
            for tab in (page, other):
                tab.click('#addFilm')
                tab.on('dialog', lambda d: d.accept())
            page.locator('[data-k="name"]').fill('Recovered first')
            page.click('#replaceSaved')
            before = stored(page)
            other.click('#replaceSaved')
            check('tabs: recovery replacement cannot overwrite a newer save',
                  stored(other) == before and 'Save conflict' in other.inner_text('#saveStatus')
                  and other.locator('#savedRecovery').is_visible())
        else:
            page.locator('[data-k="name"]').fill('Migrated first')
            before = stored(page)
            other.locator('[data-k="qty"]').fill('2')
            check('tabs: legacy migration cannot overwrite a newer save',
                  stored(other) == before and 'Save conflict' in other.inner_text('#saveStatus'))
        check('tabs: original legacy data stays intact',
              page.evaluate("localStorage.getItem('filmtube.v2')") == raw)
        page.context.close()

    page = new_page(browser)
    page.goto(URL)
    page.click('#addFilm')
    page.locator('[data-k="name"]').fill('Exact fit')
    set_setting(page, 'zoom', 1)
    for columns, cuts in ((1, True), (2, True), (2, False)):
        page.emulate_media(media='screen')
        set_setting(page, 'fullWidth', columns == 1)
        if columns == 2:
            set_setting(page, 'stripLen', 4.25)
        set_setting(page, 'showCut', cuts)
        page.locator('[data-k="qty"]').fill(str(11 * columns))
        for media in ('screen', 'print'):
            page.emulate_media(media=media)
            geometry = page.evaluate("""() => {
                const sheet=document.querySelector('.sheet').getBoundingClientRect();
                return [...document.querySelectorAll('.strip')].map(el=>{
                    const r=el.getBoundingClientRect();
                    return {left:r.left-sheet.left,right:r.right-sheet.right,
                            top:r.top-sheet.top,bottom:r.bottom-sheet.bottom,
                            width:r.width,height:r.height};
                });
            }""")
            check(f'exact fit: {columns} columns cuts={cuts} {media} borders stay inside page',
                  all(g['left'] >= -0.05 and g['right'] <= 0.05
                      and g['top'] >= -0.05 and g['bottom'] <= 0.05 for g in geometry))
            check(f'exact fit: {columns} columns cuts={cuts} {media} retains strip dimensions',
                  all(abs(g['width'] - 816 / columns) < 0.05
                      and abs(g['height'] - 96) < 0.05 for g in geometry))
        pdf = pypdf.PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
        check(f'exact fit: {columns} columns cuts={cuts} PDF keeps every label on one page',
              len(pdf.pages) == 1 and pdf.pages[0].extract_text().count('Exact fit') == 11 * columns)
    page.context.close()

def run_print_matrix(browser):
    page = new_page(browser)
    page.goto(URL)
    page.on("dialog", lambda d: d.accept())
    names = [f"Label{i:02}" for i in range(1, 24)]
    library = {"films": [{"name": name, "qty": 1} for name in names], "settings": {
        "paper": "a4", "margin": 0.25, "gap": 0.1, "fullWidth": False,
        "stripLen": 3.5, "stripH": 1, "blankEvent": False, "blankDateShot": False,
    }}
    upload(page, library)
    page.wait_for_function("document.querySelectorAll('.strip').length === 23")
    page.emulate_media(media="print")
    bounds = page.evaluate("""() => [...document.querySelectorAll('.sheet')].every(sheet => {
        const page=sheet.getBoundingClientRect();
        return [...sheet.querySelectorAll('.strip')].every(strip => {
            const r=strip.getBoundingClientRect();
            return r.left>=page.left && r.right<=page.right+1 && r.top>=page.top && r.bottom<=page.bottom+1
                && Math.abs(r.width-3.5*96)<1 && Math.abs(r.height-96)<1;
        });
    })""")
    check("A4 print: margin/gap multi-column strips keep dimensions within page", bounds)
    pdf = pypdf.PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
    texts = [p.extract_text() for p in pdf.pages]
    check("A4 print: exactly 2 pages with a partially filled final page", len(pdf.pages) == 2)
    check("A4 print: every unique label appears on its expected page once",
          len(texts) == 2 and all(texts[i // 20].count(name) == 1 for i, name in enumerate(names))
          and all("".join(texts).count(name) == 1 for name in names))
    check("A4 print: page dimensions match A4",
          all(abs(float(p.mediabox.width)/72 - 210/25.4) < 0.02
              and abs(float(p.mediabox.height)/72 - 297/25.4) < 0.02 for p in pdf.pages))
    page.context.close()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = new_page(browser)

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

    # 7c. Margin insets content within a full-page sheet without changing its width.
    page.eval_on_selector('[data-set="fullWidth"]', "el => { el.checked=true; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.eval_on_selector('[data-set="margin"]', "el => { el.value='0'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    sheet_w_m0 = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().width")
    page.eval_on_selector('[data-set="margin"]', "el => { el.value='0.15'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
    page.wait_for_timeout(40)
    sheet_w_m15 = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().width")
    strip_w_m15 = page.eval_on_selector(".strip", "el => el.getBoundingClientRect().width")
    check("margin: sheet stays full page width regardless of margin",
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
    page2 = new_page(browser)
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
    page2.on("dialog", lambda d: d.accept())
    upload(page2, lib)
    page2.wait_for_function("() => document.querySelectorAll('.film').length === 1")
    name_val = page2.eval_on_selector('.film input[data-k="name"]', "el => el.value")
    strip_cnt = page2.eval_on_selector_all(".strip", "els => els.length")
    check("import: film loaded from JSON", name_val == "TEST FILM XYZ", name_val)
    check("import: qty 3 -> 3 strips", strip_cnt == 3, f"strips={strip_cnt}")

    # 15. Import hardening: malformed (films not an array) is rejected, no crash
    upload(page2, {"films": {"not": "an array"}})
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
    #     exact Letter sizing and all expected sample labels.
    page3 = new_page(browser)
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
    check("print PDF: samples produce exactly 3 pages matching the preview",
          pdf_pages == dom_sheets == 3, f"dom_sheets={dom_sheets} pdf_pages={pdf_pages}")
    check("print PDF: every page is exactly 8.5x11in (Letter)",
          boxes == {(8.5, 11.0)}, f"boxes={boxes}")

    check("print PDF: every sample label appears once per roll, with no blank pages",
          all(p.extract_text().strip() for p in rdr.pages)
          and sum(p.extract_text().count("Kodak Portra 400") for p in rdr.pages) == 5
          and sum(p.extract_text().count("Kodak Gold 200") for p in rdr.pages) == 8
          and sum(p.extract_text().count("Ilford HP5 Plus") for p in rdr.pages) == 4
          and sum(p.extract_text().count("Fujifilm Superia") for p in rdr.pages) == 6)

    # Further regression scenarios below use their own clean browser profiles.
    run_reliability_checks(browser)
    run_print_matrix(browser)
    run_review_regressions(browser)
    check("all pages: no console/page errors", not console_errors, str(console_errors))
    check("offline: no HTTP(S) requests attempted", not network_requests, str(network_requests))
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
