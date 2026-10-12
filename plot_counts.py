"""
Interactive week-by-week chart of rec center occupancy (Monday - Sunday).

Setup (once):
    pip install pandas plotly

Usage:
    python plot_counts.py                        # reads rec_counts.csv, writes rec_counts_chart.html, opens it
    python plot_counts.py data.csv chart.html    # choose your own file names
    python plot_counts.py --no-open              # write the file but don't launch the browser

The CSV must be in the one-row-per-reading layout:
    logged_at,site_last_updated,<facility 1>,<facility 2>,...
(If yours is still the old one-row-per-facility layout, run convert_csv.py first.)
"""
import sys
import pathlib
import webbrowser

import pandas as pd
import plotly.graph_objects as go

args = [a for a in sys.argv[1:] if not a.startswith("--")]
open_browser = "--no-open" not in sys.argv
csv_path = pathlib.Path(args[0] if len(args) > 0 else "rec_counts.csv")
html_path = pathlib.Path(args[1] if len(args) > 1 else "rec_counts_chart.html")

# Facilities drawn when the chart first opens. Every other facility is still
# plotted, just switched off: click its name in the legend to turn it on.
DEFAULT_VISIBLE = ["Raider Power Zone", "Machine Weight Room", "Free Weight Room"]

# Hours when the rec center is closed: (start_hour, end_hour) on a 24-hour clock,
# so (0, 6) means midnight up to 6:00am. Readings logged in this window are left
# off the chart, and the lines break there, leaving a gap each night. Lines stay
# connected the rest of the day. Set to None to connect everything, closed hours too.
CLOSED_HOURS = (0, 6)

# Time-of-day labels along the x axis, in addition to the day labels: one every
# this many hours, counted from midnight (4 -> 12 AM, 4 AM, 8 AM, 12 PM, 4 PM, 8 PM).
# Hours inside CLOSED_HOURS are skipped, since nothing is plotted then. Noon is always
# labelled because the day name and date sit under it. None = day labels only.
HOUR_TICK_EVERY = 4

# Vertical line colors: a dark line at each midnight (day separator) and a light
# gray line at each time label. Any CSS color works, e.g. "black" or "#000000".
DAY_LINE_COLOR = "#333333"
HOUR_LINE_COLOR = "#C4C4C4"

# ---------------------------------------------------------------- load data
if not csv_path.exists():
    sys.exit(f"Can't find {csv_path}")

df = pd.read_csv(csv_path, encoding="utf-8-sig")  # utf-8-sig strips Excel's hidden BOM
df.columns = [c.strip() for c in df.columns]

if "facility" in df.columns:
    sys.exit("This file is in the old one-row-per-facility layout. "
             "Run convert_csv.py on it first.")
if "logged_at" not in df.columns:
    sys.exit(f"No 'logged_at' column found. Columns are: {list(df.columns)}")

df["logged_at"] = pd.to_datetime(df["logged_at"], errors="coerce")
df = df.dropna(subset=["logged_at"]).sort_values("logged_at")
if df.empty:
    sys.exit("No readable rows in the CSV.")

# Every column that isn't one of the two fixed ones is a facility
facilities = [c for c in df.columns if c not in ("logged_at", "site_last_updated")]
for c in facilities:
    df[c] = pd.to_numeric(df[c], errors="coerce")  # blanks / junk become NaN


# ---------------------------------------------------------------- weeks
def monday_of(ts):
    """
    Midnight on the Monday that starts ts's week:
        monday = date - weekday     (weekday: Mon=0, Tue=1, ... Sun=6)
    Example: Sunday Oct 11 has weekday 6, so Oct 11 - 6 days = Monday Oct 5.
    """
    d = ts.normalize()
    return d - pd.Timedelta(days=d.weekday())


first_monday = monday_of(df["logged_at"].min())
last_monday = monday_of(df["logged_at"].max())
weeks = list(pd.date_range(first_monday, last_monday, freq="7D"))


# ---------------------------------------------------------------- traces
fig = go.Figure()

# Drop readings logged while the rec center is closed (closed if start <= hour < end).
if CLOSED_HOURS is not None:
    hours = df["logged_at"].dt.hour
    plot_df = df[~((hours >= CLOSED_HOURS[0]) & (hours < CLOSED_HOURS[1]))]
else:
    plot_df = df


def with_closed_breaks(sub, col):
    """
    x/y lists for one facility. With closed-hour readings removed, two consecutive
    readings on different calendar days means the line would cross a closed night,
    so a None is inserted there. plotly leaves a break at a None.
    """
    xs, ys, prev = [], [], None
    for t, v in zip(sub["logged_at"], sub[col]):
        if CLOSED_HOURS is not None and prev is not None and t.normalize() != prev.normalize():
            xs.append(t.normalize())  # midnight that starts the new day
            ys.append(None)           # break the line here
        xs.append(t)
        ys.append(v)
        prev = t
    return xs, ys


# Invisible helper trace: it draws nothing, but adds a "Site last updated" line
# to the hover box showing the time the website itself reported for that reading.
fig.add_trace(go.Scatter(
    x=plot_df["logged_at"], y=[0] * len(plot_df), name="Site last updated",
    mode="markers", marker=dict(opacity=0), showlegend=False,
    customdata=plot_df["site_last_updated"].fillna("").astype(str),
    hovertemplate="%{customdata}",
))

# Which facilities start switched on. If none of the names above match the CSV
# (say the website renamed them), fall back to showing everything.
shown = [f for f in DEFAULT_VISIBLE if f in facilities]
for f in DEFAULT_VISIBLE:
    if f not in facilities:
        print(f"Warning: '{f}' is in DEFAULT_VISIBLE but not in the CSV columns.")
if not shown:
    shown = list(facilities)

# Plot the switched-on facilities first, in the order listed in DEFAULT_VISIBLE,
# then everything else in CSV order. plotly lists traces in the order they are
# added, so this puts the active ones at the top of the legend and the hover box.
ordered = shown + [f for f in facilities if f not in shown]

for name in ordered:
    sub = plot_df[["logged_at", name]].dropna()
    xs, ys = with_closed_breaks(sub, name)
    fig.add_trace(go.Scatter(
        x=xs, y=ys, name=name, mode="lines+markers",
        marker=dict(size=4), line=dict(width=2),
        connectgaps=False,  # keep the break at each closed night
        # "legendonly" = drawn but switched off; click the legend name to show it
        visible=True if name in shown else "legendonly",
        hovertemplate="%{y:.0f}%",
    ))

# ---------------------------------------------------------------- week view
ts_fmt = "%Y-%m-%d %H:%M:%S"


def hour_label(h):
    """0 -> '12 AM', 4 -> '4 AM', 12 -> '12 PM', 16 -> '4 PM'  (h % 12 maps 0 to 12)."""
    return f"{(h % 12) or 12} {'AM' if h < 12 else 'PM'}"


def tick_hours():
    """Hours of the day (0-23) that get a time label; see HOUR_TICK_EVERY above."""
    hours = set() if HOUR_TICK_EVERY is None else set(range(0, 24, HOUR_TICK_EVERY))
    if CLOSED_HOURS is not None:
        hours = {h for h in hours if not (CLOSED_HOURS[0] <= h < CLOSED_HOURS[1])}
    hours.add(12)  # noon always gets a tick: it is where the day name goes
    return sorted(hours)


def week_view(ws):
    """
    Axis settings for the week starting on Monday `ws` (midnight):
      - range runs from Monday 00:00:00 to Sunday 23:59:59, nothing past Sunday
      - a time label at each hour in tick_hours() on every day
      - the noon label also carries the day name and date underneath, so those sit
        in the middle of their day (tick position = day midnight + 12 h)
    """
    days = [ws + pd.Timedelta(days=i) for i in range(7)]
    hours = tick_hours()
    tickvals, ticktext = [], []
    for d in days:
        for h in hours:
            tickvals.append((d + pd.Timedelta(hours=h)).strftime(ts_fmt))
            if h == 12:
                ticktext.append(f"{hour_label(h)}<br><b>{d:%a}</b><br>{d:%b %d}")
            else:
                ticktext.append(hour_label(h))
    return {
        "xaxis.range": [ws.strftime(ts_fmt),
                        (ws + pd.Timedelta(days=7, seconds=-1)).strftime(ts_fmt)],
        "xaxis.tickvals": tickvals,
        "xaxis.ticktext": ticktext,
    }


# Faint vertical line at every midnight, so each day is a labelled column.
# (Gridlines can't be used for this: they sit on the ticks, which are now at noon.)
day_lines = [
    dict(type="line", xref="x", yref="paper", y0=0, y1=1,
         x0=m.strftime(ts_fmt), x1=m.strftime(ts_fmt),
         # "above" draws these over the gridlines and the data lines. ("between" would
         # keep them over the gridlines but under the data lines.)
         line=dict(color=DAY_LINE_COLOR, width=1.5), layer="above")
    for m in pd.date_range(first_monday, last_monday + pd.Timedelta(days=7), freq="D")
]

# ---------------------------------------------------------------- week picker
# Each dropdown entry re-zooms the chart to that Monday-Sunday and moves the day labels.
buttons = []
for ws in reversed(weeks):  # newest week first
    label = f"Mon {ws:%b %d} - Sun {(ws + pd.Timedelta(days=6)):%b %d, %Y}"
    buttons.append(dict(label=label, method="relayout", args=[week_view(ws)]))

latest = weeks[-1]
latest_view = week_view(latest)
y_top = max(100, float(df[facilities].max().max()) * 1.05)

fig.update_layout(
    title="University Recreation occupancy by week (Monday - Sunday)",
    shapes=day_lines,
    xaxis=dict(
        range=latest_view["xaxis.range"],
        tickmode="array",
        tickvals=latest_view["xaxis.tickvals"],
        ticktext=latest_view["xaxis.ticktext"],
        ticks="outside", ticklen=4,  # small tick mark at each time label
        tickangle=0,            # keep labels horizontal (plotly may otherwise rotate them)
        automargin=True,        # leave room for the three-line noon label
        showgrid=True,          # light gray line at each time label (the tick positions)
        gridcolor=HOUR_LINE_COLOR, gridwidth=1,
        hoverformat="%a %b %d, %I:%M %p",  # header of the hover box: when we logged it
        title="Time",
    ),
    yaxis=dict(title="Occupancy (%)", range=[0, y_top], dtick=10),  # label + gridline every 10%
    hovermode="x unified",
    height=650,
    legend=dict(title="Click a name to show/hide"),
    updatemenus=[dict(
        type="dropdown", active=0, buttons=buttons,
        x=0.0, xanchor="left", y=1.14, yanchor="top",
    )],
    annotations=[dict(
        text="Week:", x=0.0, xref="paper", y=1.16, yref="paper",
        showarrow=False, xanchor="right",
    )],
    margin=dict(t=110),
)

# include_plotlyjs=True bundles the plotting library into the file (~3.5 MB),
# so the chart works offline and can be emailed as a single file.
fig.write_html(html_path, include_plotlyjs=True, auto_open=False)

print(f"{len(df)} readings, {len(facilities)} facilities, "
      f"{len(weeks)} week(s): {first_monday:%b %d, %Y} - "
      f"{(last_monday + pd.Timedelta(days=6)):%b %d, %Y}")
print(f"Wrote {html_path}")
if open_browser:
    webbrowser.open(html_path.resolve().as_uri())
