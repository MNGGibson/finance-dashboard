"""Shared look and feel: design tokens, page chrome, stat tiles and chart styling.

Every page calls `apply_page_style()` once, builds tiles with `stat_tile()` /
`tile_row()`, and passes Altair charts through `style_chart()` so the whole app reads
as one system. Colours are a validated dark-surface palette: series colours identify
data, status colours are reserved for good/bad, and text always uses the ink tokens.
"""
import html

import altair as alt
import streamlit as st

# ---------- Tokens ----------
PAGE = "#0d0d0d"
SURFACE = "#1a1a19"
INK = "#ffffff"
INK_SECONDARY = "#c3c2b7"
INK_MUTED = "#898781"
GRID = "#2c2c2a"
AXIS = "#383835"
BORDER = "rgba(255,255,255,0.10)"

SERIES = {"blue": "#3987e5", "orange": "#d95926", "aqua": "#199e70"}
ACCENT = SERIES["blue"]
DEEMPHASIS = "#6b6a65"  # context marks when one series is the point

GOOD = "#0ca30c"
CRITICAL = "#e66767"
WARNING = "#fab219"

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def money(value, cents=False):
    """$1,234 or -$1,234 (sign before the symbol, never $-1,234)."""
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}" if cents else f"{sign}${abs(value):,.0f}"


def apply_page_style():
    st.markdown(
        f"""
<style>
.block-container {{ padding-top: 3.6rem; padding-bottom: 3rem; max-width: 1280px; }}
h1 {{ font-size: 1.7rem !important; font-weight: 650 !important; letter-spacing: -0.01em; padding: 0 0 0.35rem 0 !important; }}
h3 {{ font-size: 1rem !important; font-weight: 600 !important; padding: 0 !important; margin: 0 0 2px 0 !important; }}
[data-testid="stCaptionContainer"] {{ color: {INK_MUTED}; }}

/* Cards: any st.container(border=True, key="card_...") */
[class*="st-key-card_"] {{
    background: {SURFACE};
    border: 1px solid {BORDER} !important;
    border-radius: 14px;
    padding: 1.1rem 1.25rem 1rem 1.25rem;
}}

.section-label {{
    font-size: 0.78rem; font-weight: 600; color: {INK_MUTED};
    text-transform: uppercase; letter-spacing: 0.06em; margin: 1.4rem 0 0.6rem 0;
}}

/* Hero */
.hero-label {{ font-size: 0.9rem; color: {INK_SECONDARY}; margin: 0; }}
.hero-value {{ font-size: 3.2rem; font-weight: 650; letter-spacing: -0.03em; line-height: 1.1; margin: 2px 0 6px 0; color: {INK}; }}
.hero-sub {{ font-size: 0.88rem; color: {INK_MUTED}; margin: 0; }}

/* Stat tiles */
.tile-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
.tile {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px;
    padding: 14px 16px 13px 16px; min-width: 0;
}}
.tile-label {{ font-size: 0.85rem; color: {INK_SECONDARY}; margin: 0 0 6px 0; }}
.tile-value {{ font-size: 1.7rem; font-weight: 650; letter-spacing: -0.02em; line-height: 1.15; margin: 0; color: {INK}; }}
.tile-note {{ font-size: 0.8rem; color: {INK_MUTED}; margin: 6px 0 0 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.delta {{ font-weight: 600; }}
.delta.good {{ color: {GOOD}; }}
.delta.bad {{ color: {CRITICAL}; }}
.delta.flat {{ color: {INK_MUTED}; }}

/* Composition meter (assets vs debt) */
.meter {{ display: flex; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; margin: 14px 0 10px 0; }}
.meter > span {{ display: block; height: 100%; }}
.legend {{ display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.85rem; color: {INK_SECONDARY}; }}
.legend b {{ color: {INK}; font-weight: 600; }}
.swatch {{ display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 7px; }}

/* Account list */
.acct-group {{ font-size: 0.78rem; color: {INK_MUTED}; text-transform: uppercase; letter-spacing: 0.06em;
    display: flex; justify-content: space-between; margin: 14px 0 4px 0; }}
.acct-group:first-child {{ margin-top: 4px; }}
.acct {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
    padding: 9px 0; border-top: 1px solid {GRID}; }}
.acct-name {{ font-size: 0.92rem; color: {INK}; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.acct-org {{ font-size: 0.78rem; color: {INK_MUTED}; }}
.acct-bal {{ font-size: 0.95rem; font-weight: 600; color: {INK}; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.badge {{ font-size: 0.72rem; color: {WARNING}; border: 1px solid rgba(250,178,25,0.35);
    border-radius: 999px; padding: 1px 8px; margin-left: 8px; white-space: nowrap; }}

/* Status line (icon + label, never colour alone) */
.status {{ font-size: 0.92rem; color: {INK_SECONDARY}; margin: 6px 0 0 0; }}
.status .good {{ color: {GOOD}; font-weight: 600; }}
.status .bad {{ color: {CRITICAL}; font-weight: 600; }}
</style>
""",
        unsafe_allow_html=True,
    )


def delta_html(current, previous, up_is_good, versus):
    """Signed change vs a named period. Colour = direction x whether up is good."""
    if previous is None or previous == 0:
        return f'<span class="delta flat">No {html.escape(versus)} data</span>'
    change = current - previous
    if abs(change) < 0.5:
        return f'<span class="delta flat">No change</span> vs {html.escape(versus)}'
    up = change > 0
    # up_is_good=None: a change that is neither good nor bad in itself, so no verdict colour.
    tone = "flat" if up_is_good is None else ("good" if up == up_is_good else "bad")
    arrow = "▲" if up else "▼"
    pct = abs(change) / abs(previous) * 100
    exact = f"{money(previous)} then, {money(current)} now"
    return (
        f'<span title="{html.escape(exact)}"><span class="delta {tone}">{arrow} {pct:.0f}%</span> '
        f"vs {html.escape(versus)}</span>"
    )


def stat_tile(label, value, note_html=""):
    note = f'<div class="tile-note">{note_html}</div>' if note_html else ""
    return (
        f'<div class="tile"><div class="tile-label">{html.escape(label)}</div>'
        f'<div class="tile-value">{html.escape(value)}</div>{note}</div>'
    )


def tile_row(tiles, min_width=190):
    """Tiles share the row equally and wrap only when narrower than `min_width` px."""
    columns = f"grid-template-columns: repeat(auto-fit, minmax({min_width}px, 1fr))"
    st.markdown(f'<div class="tile-row" style="{columns}">{"".join(tiles)}</div>', unsafe_allow_html=True)


def section_label(text):
    st.markdown(f'<div class="section-label">{html.escape(text)}</div>', unsafe_allow_html=True)


def style_chart(chart, height=None):
    """Recessive chrome: transparent surface, hairline solid grid, muted axis text."""
    if height is not None:
        chart = chart.properties(height=height)
    return (
        chart.configure(background="transparent", font=FONT, padding={"left": 0, "right": 8, "top": 6, "bottom": 0})
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=12, titleFontSize=12,
            titleFontWeight="normal", gridColor=GRID, gridDash=[], domainColor=AXIS,
            tickColor=AXIS, tickSize=4, labelPadding=6,
        )
        .configure_legend(
            labelColor=INK_SECONDARY, titleColor=INK_MUTED, labelFontSize=12, symbolType="square",
            symbolSize=90, orient="top", direction="horizontal", title=None, padding=0, offset=8,
        )
    )


def show_chart(chart, height=None, key=None, selection=None, on_select="rerun"):
    """Render a chart. With `selection` (the name of a selection parameter on the chart),
    clicks are reported back and the chart's event is returned; read it with `picked()`."""
    styled = style_chart(chart, height)
    if selection is None:
        st.altair_chart(styled, width="stretch", theme=None)
        return None
    return st.altair_chart(styled, width="stretch", theme=None,
                           key=key, on_select=on_select, selection_mode=selection)


def picked(event, selection, field):
    """The clicked value of `field`, or None when nothing is selected."""
    points = (event or {}).get("selection", {}).get(selection) or []
    return points[0].get(field) if points else None


def click_and_hover(field):
    """The two selection parameters every clickable chart uses: `pick` (click to select,
    click again or click empty space to clear) and `hover` (so the mark visibly responds)."""
    pick = alt.selection_point(name="pick", fields=[field], on="click")
    hover = alt.selection_point(name="hover", fields=[field], on="mouseover", clear="mouseout", empty=False)
    return pick, hover
