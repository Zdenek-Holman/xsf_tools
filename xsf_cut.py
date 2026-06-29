#!/usr/bin/env python3
"""Cut a region from the first 3-D DATAGRID block in an XSF file."""

from __future__ import annotations

from pathlib import Path

from xsf_tools import cut_xsf_text


# =============================================================================
# USER PARAMETERS
# =============================================================================

INPUT_FILE = "energy_grid.xsf"
OUTPUT_FILE = "energy_grid_region.xsf"

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

OUTSIDE_VALUE = 0.0

# Set to a number (for example -60.0) to fill the selected region with a
# constant. Leave as None to retain the original data inside the cut.
TEST_VALUE = None


def main() -> None:
    input_text = Path(INPUT_FILE).read_text(encoding="utf-8")
    output_text, stats = cut_xsf_text(
        input_text,
        BOUNDS,
        coordinate_mode=COORDINATE_MODE,
        outside_value=OUTSIDE_VALUE,
        test_value=TEST_VALUE,
        source_name=INPUT_FILE,
    )
    Path(OUTPUT_FILE).write_text(output_text, encoding="utf-8")

    print(
        f"Done: {OUTPUT_FILE} ({stats.selected_points}/{stats.total_points} "
        f"grid points selected, {stats.coordinate_mode} bounds)"
    )


if __name__ == "__main__":
    main()
