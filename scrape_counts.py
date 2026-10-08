"""
Log TTU Rec "Live Facility Counts" to a CSV that Excel can open.

Setup (once):
    pip install playwright
    playwright install chromium

Step 1 - see what the page actually renders:
    python scrape_counts.py --discover

Step 2 - log once, or loop every 30 minutes:
    python scrape_counts.py
    python scrape_counts.py --loop
"""
import csv
import re
import sys
import time
import pathlib
from datetime import datetime
from playwright.sync_api import sync_playwright

URL = "https://www.depts.ttu.edu/recreation/facilities/hours.php"
CSV_PATH = pathlib.Path("rec_counts.csv")
INTERVAL_SECONDS = 30 * 60


def render_all_text(page):
    """Return [(frame_url, visible_text)] for the main page and every iframe."""
    out = []
    for frame in page.frames:
        try:
            out.append((frame.url, frame.inner_text("body")))
        except Exception:
            pass  # frame may be cross-origin or empty
    return out


def parse_counts(text):
    """
    The live-counts section looks like this (3 lines per facility):

        Raider Power Zone
        Last Updated: 10:50 PM
        24%

    Returns [(facility, last_updated, percent_full), ...]
    """
    # Keep only the text between the two section headings
    start = text.find("LIVE FACILITY COUNTS")
    end = text.find("UNIVERSITY RECREATION HOURS", start)
    section = text[start:end] if start != -1 else text

    pattern = re.compile(
        r"^(?P<name>.+?)\s*\n"            # facility name on its own line
        r"Last Updated:\s*(?P<updated>.+?)\s*\n"  # the site's own timestamp
        r"(?P<pct>\d+)%",                   # percentage, digits before the %
        re.MULTILINE,
    )
    return [(m["name"].strip(), m["updated"].strip(), int(m["pct"]))
            for m in pattern.finditer(section)]


def scrape_once():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.get_by_text("Last Updated").first.wait_for(timeout=30000)
        frames = render_all_text(page)
        browser.close()
    return frames


FIXED_COLS = ["logged_at", "site_last_updated"]


def read_csv():
    """Return (header_list, list_of_row_dicts) from the CSV, or ([], []) if none."""
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        return [], []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(fieldnames, rows):
    """Rewrite the whole CSV (used for first creation, conversion, new columns)."""
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        w.writeheader()
        w.writerows(rows)


def append_row(readings):
    """
    readings = [(facility, site_last_updated, percent), ...] from one scrape.
    Writes ONE row containing every facility, unless the site's "Last Updated"
    values are the same as in the most recent row. Returns 1 if a row was
    added, 0 if skipped.
    """
    fieldnames, rows = read_csv()
    rewrite = False  # True when the whole file must be rewritten (new file / new column)

    # Refuse to touch a file still in the old one-row-per-facility layout
    if "facility" in fieldnames:
        raise RuntimeError(
            f"{CSV_PATH} is in the old format. Run convert_csv.py on it first."
        )

    # Combine the site's update times into one string, e.g. "10:50 PM"
    # (if facilities disagree: "10:50 PM / 10:55 PM")
    updated_values = []
    for _, updated, _ in readings:
        if updated not in updated_values:
            updated_values.append(updated)
    updated_str = " / ".join(updated_values)

    # Skip if the site hasn't refreshed since the last logged row
    if rows and rows[-1].get("site_last_updated") == updated_str:
        return 0

    # Build the single new row
    row = {"logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "site_last_updated": updated_str}
    if not fieldnames:
        fieldnames = list(FIXED_COLS)
        rewrite = True  # brand-new file needs a header
    for name, _, pct in readings:
        row[name] = pct
        if name not in fieldnames:  # a facility we haven't seen before
            fieldnames.append(name)
            rewrite = True

    if rewrite:
        write_csv(fieldnames, rows + [row])
    else:
        with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames, restval="").writerow(row)
    return 1


def main():
    frames = scrape_once()

    if "--discover" in sys.argv:
        for url, text in frames:
            print("=" * 70)
            print("FRAME:", url)
            print("-" * 70)
            print(text)
        return

    # Only parse frames that mention the counts section
    rows = []
    for url, text in frames:
        if "LIVE FACILITY COUNTS" in text:
            rows.extend(parse_counts(text))
    if not rows:
        print("No counts parsed. Run with --discover and check the output.")
        return
    added = append_row(rows)
    if added:
        print(f"{datetime.now():%H:%M:%S} added 1 row ({len(rows)} facilities) to {CSV_PATH}")
    else:
        print(f"{datetime.now():%H:%M:%S} site not updated since last row; nothing added")

if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            try:
                main()
            except Exception as e:
                print("Error:", e)
            time.sleep(INTERVAL_SECONDS)
    else:
        main()
