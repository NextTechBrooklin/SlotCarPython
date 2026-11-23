"""Design tokens: colours and typography for the whole app.

Everything visual pulls from here so the look can be re-skinned in one place.
"""

from __future__ import annotations

# --- Surfaces -------------------------------------------------------------
BG = "#0a0c11"            # window background (asphalt black)
HEADER_BG = "#07080c"
SURFACE = "#12161e"       # cards / panels
SURFACE_2 = "#1a1f2a"     # raised elements, inputs
SURFACE_3 = "#232a37"     # hover
BORDER = "#252c3a"
BORDER_STRONG = "#343d4f"

# --- Text -----------------------------------------------------------------
TEXT = "#eef1f6"
TEXT_MUTED = "#8b94a7"
TEXT_FAINT = "#5a6376"

# --- Brand / racing accents ----------------------------------------------
ACCENT = "#ff2a3c"        # racing red
ACCENT_HOVER = "#ff4a5a"
GO_GREEN = "#14d27a"
GO_GREEN_HOVER = "#2ee891"
AMBER = "#ffb21c"
PURPLE = "#b45cff"        # "fastest lap" purple, as in F1 timing screens
DANGER = "#ff4d4d"

LANE_COLORS = {
    1: "#22d3ee",         # Lane 1 - cyan
    2: "#ff7a1a",         # Lane 2 - orange
}

# Tachometer LED ramp
GAUGE_LOW = "#14d27a"
GAUGE_MID = "#ffb21c"
GAUGE_HIGH = "#ff2a3c"
GAUGE_OFF = "#1c222d"

# --- Typography -----------------------------------------------------------
DISPLAY_FAMILY = "Bahnschrift SemiBold Condensed"
DISPLAY_BOLD = "Bahnschrift Condensed"
UI_FAMILY = "Segoe UI Variable Text"
UI_SEMIBOLD = "Segoe UI Semibold"
MONO_FAMILY = "Cascadia Mono"
DIGITS_FAMILY = "Bahnschrift SemiBold SemiConden"


def mix(hex_a: str, hex_b: str, t: float) -> str:
    """Linear blend between two ``#rrggbb`` colours (t=0 -> a, t=1 -> b)."""
    t = max(0.0, min(1.0, t))
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
