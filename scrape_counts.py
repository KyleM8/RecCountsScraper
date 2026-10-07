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


def last_logged_updates():
    """
    Read the existing CSV and return {facility: most recent site_last_updated}.
    Later rows overwrite earlier ones, so the dict ends up holding the newest.
    """
    if not CSV_PATH.exists():
        return {}
    last = {}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            last[row["facility"]] = row["site_last_updated"]
    return last


def append_rows(rows):
    """Append only readings whose 'Last Updated' differs from the last one logged."""
    last = last_logged_updates()
    new_rows = []
    for name, updated, pct in rows:
        if last.get(name) == updated:
            continue  # site hasn't refreshed this facility; skip it
        new_rows.append((name, updated, pct))
        last[name] = updated  # also guards against duplicates within one run

    if not new_rows:
        return 0

    new_file = not CSV_PATH.exists()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["logged_at", "facility", "site_last_updated", "percent_full"])
        for name, updated, pct in new_rows:
            w.writerow([stamp, name, updated, pct])
    return len(new_rows)


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
    added = append_rows(rows)
    skipped = len(rows) - added
    print(f"{datetime.now():%H:%M:%S} added {added} new rows, "
          f"skipped {skipped} unchanged, in {CSV_PATH}")


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
