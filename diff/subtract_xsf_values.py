#!/usr/bin/env python3
"""Subtract XSF map values without checking the simulation box."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xsf_tools import default_subtract_output_path, subtract_xsf_file_paths


def print_options(file=sys.stderr) -> None:
    print(
        "Subtract XSF map values without checking the simulation box.\n"
        "\n"
        "The operation is:\n"
        "    result = (map A + offset A) - (map B + offset B)\n"
        "\n"
        "Examples:\n"
        "python3 subtract_xsf_values.py A.xsf B.xsf -o difference.xsf\n"
        "python3 subtract_xsf_values.py A.xsf B.xsf --offset-a 2.5 --offset-b -1.25 -o difference.xsf\n"
        "python3 subtract_xsf_values.py A.xsf B.xsf --align-minima -o aligned_difference.xsf\n",
        file=file,
    )


class XSFArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print_options()
        self.exit(2, f"Error: {message}\n")


def default_output_path(map_a: Path, map_b: Path) -> Path:
    return default_subtract_output_path(map_a, map_b)


def build_parser() -> argparse.ArgumentParser:
    parser = XSFArgumentParser(
        description=(
            "Subtract XSF data values only: "
            "(A + offset-a) - (B + offset-b)."
        )
    )
    parser.add_argument("map_a", type=Path, help="first XSF map")
    parser.add_argument("map_b", type=Path, help="second XSF map")
    parser.add_argument("-o", "--output", type=Path, help="output XSF path")
    parser.add_argument(
        "--offset-a",
        type=float,
        default=0.0,
        help="energy in eV added to every value in map A",
    )
    parser.add_argument(
        "--offset-b",
        type=float,
        default=0.0,
        help="energy in eV added to every value in map B",
    )
    parser.add_argument(
        "--align-minima",
        action="store_true",
        help="shift each map so its minimum is 0 eV before subtraction",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the output file if it already exists",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output_path, stats = subtract_xsf_file_paths(
            args.map_a,
            args.map_b,
            output_path=args.output,
            offset_a=args.offset_a,
            offset_b=args.offset_b,
            align_minima=args.align_minima,
            force=args.force,
        )

        print(f"Values:     {stats.values}")
        print(f"Map A min:  {stats.map_a_min:.7f} eV")
        print(f"Map B min:  {stats.map_b_min:.7f} eV")
        print(f"Offset A:   {stats.offset_a:+.7f} eV")
        print(f"Offset B:   {stats.offset_b:+.7f} eV")
        print(f"Result:     {stats.result_min:.7f} to {stats.result_max:.7f} eV")
        print(f"Written:    {output_path}")
        return 0
    except ValueError as error:
        print_options()
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
