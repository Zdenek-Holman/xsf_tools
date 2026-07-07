#!/usr/bin/env python3
"""Cut a region from the first 3-D DATAGRID block in an XSF file."""

from __future__ import annotations

from pathlib import Path

from xsf_tools import cut_xsf_box_text, cut_xsf_text


# =============================================================================
# USER PARAMETERS
# =============================================================================

INPUT_FILE = "energy_grid.xsf"
OUTPUT_FILE = "energy_grid_region.xsf"

# "bounds": old axis-aligned cut controlled by BOUNDS below.
# "box":    4-point oblique box/parallelepiped controlled by POINT_A/B/C/D.
CUT_MODE = "bounds"

# "cartesian": bounds are x, y, z coordinates in Angstrom.
# "fractional": bounds are coordinates along the three DATAGRID vectors.
#               A range of 0.0 to 1.0 covers the complete unit cell.
#
# Fractional mode is useful for hexagonal/oblique cells because the cut follows
# the lattice vectors instead of the Cartesian x/y/z axes.
COORDINATE_MODE = "cartesian"

BOUNDS = (
    (-100.0, 100.0),  # x or fractional coordinate along grid vector 1
    (-100.0, 100.0),  # y or fractional coordinate along grid vector 2
    (5.0, 6.0),       # z or fractional coordinate along grid vector 3
)

# Used only when CUT_MODE = "box".
#
# "cartesian": points are x, y, z coordinates in Angstrom.
# "fractional": points are coordinates along the three DATAGRID vectors.
POINT_MODE = "cartesian"

# The 4-point box is interpreted as:
#
#   u = POINT_B - POINT_A
#   v = POINT_C - POINT_B
#   w = POINT_D - POINT_A
#
# A grid point P is kept when:
#
#   P = POINT_A + s*u + t*v + r*w, where 0 <= s,t,r <= 1
#
# Full-cell example in fractional mode:
#
#   POINT_MODE = "fractional"
#   POINT_A = (0.0, 0.0, 0.0)
#   POINT_B = (1.0, 0.0, 0.0)
#   POINT_C = (1.0, 1.0, 0.0)
#   POINT_D = (0.0, 0.0, 1.0)
POINT_A = (0.0, 0.0, 0.0)
POINT_B = (1.0, 0.0, 0.0)
POINT_C = (1.0, 1.0, 0.0)
POINT_D = (0.0, 0.0, 1.0)

OUTSIDE_VALUE = 0.0

# Set to a number (for example -60.0) to fill the selected region with a
# constant. Leave as None to retain the original data inside the cut.
TEST_VALUE = None


def main() -> None:
    input_text = Path(INPUT_FILE).read_text(encoding="utf-8")
    mode = CUT_MODE.lower()
    if mode == "bounds":
        output_text, stats = cut_xsf_text(
            input_text,
            BOUNDS,
            coordinate_mode=COORDINATE_MODE,
            outside_value=OUTSIDE_VALUE,
            test_value=TEST_VALUE,
            source_name=INPUT_FILE,
        )
    elif mode == "box":
        output_text, stats = cut_xsf_box_text(
            input_text,
            POINT_A,
            POINT_B,
            POINT_C,
            POINT_D,
            point_mode=POINT_MODE,
            outside_value=OUTSIDE_VALUE,
            test_value=TEST_VALUE,
            source_name=INPUT_FILE,
        )
    else:
        raise ValueError(f"Unknown CUT_MODE {CUT_MODE!r}; use 'bounds' or 'box'")

    Path(OUTPUT_FILE).write_text(output_text, encoding="utf-8")

    print(
        f"Done: {OUTPUT_FILE} ({stats.selected_points}/{stats.total_points} "
        f"grid points selected, {stats.coordinate_mode})"
    )


if __name__ == "__main__":
    main()
