#!/usr/bin/env python3
"""Subtract two three-dimensional XSF data grids.

The operation is:

    result = (map A + offset A) - (map B + offset B)

Alternatively, ``--align-minima`` shifts both maps so that their minimum
energy is zero before subtraction.

If you want to have autocompletion for the command-line arguments, run: source structure_tools_completion.sh
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class XSFGrid:
    path: Path
    prefix: list[str]
    block_name: str
    datagrid_name: str
    dimensions: tuple[int, int, int]
    origin: tuple[float, float, float]
    vectors: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    values: list[float]


def print_options(file=sys.stderr):
    print(
        "Subtract two three-dimensional XSF data grids.\n"
        "\n"
        "The operation is:\n"
        "    result = (map A + offset A) - (map B + offset B)\n"
        "Alternatively, --align-minima shifts both maps so that their minimum energy is zero before subtraction.\n"
        "\n"
        "Example usage:\n"
        "subtract_xsf A.xsf B.xsf\n"
        "subtract_xsf A.xsf B.xsf --offset-a 2.5 --offset-b -1.25 -o difference.xsf\n"
        "subtract_xsf A.xsf B.xsf --align-minima -o aligned_difference.xsf\n"
        "\n",
        "If you want to have autocompletion for the command-line arguments (locally), run: source structure_tools_completion.sh"
        "\n",
        file=file,      
        )


class XSFArgumentParser(argparse.ArgumentParser):
    """Argument parser that uses the script's concise error guide."""

    def error(self, message: str) -> None:
        print_options()
        self.exit(2, f"Error: {message}\n")


def parse_vector(line: str, description: str, path: Path) -> tuple[float, float, float]:
    fields = line.split()
    if len(fields) != 3:
        raise ValueError(f"{path}: invalid {description}: {line!r}")
    try:
        return tuple(float(value) for value in fields)  # type: ignore[return-value]
    except ValueError as error:
        raise ValueError(f"{path}: nonnumeric {description}: {line!r}") from error


def read_xsf(path: Path) -> XSFGrid:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error

    begin_block = next(
        (i for i, line in enumerate(lines) if line.strip() == "BEGIN_BLOCK_DATAGRID_3D"),
        None,
    )
    if begin_block is None:
        raise ValueError(f"{path}: BEGIN_BLOCK_DATAGRID_3D was not found")

    begin_grid = next(
        (
            i
            for i in range(begin_block + 1, len(lines))
            if lines[i].strip().startswith("BEGIN_DATAGRID_3D")
        ),
        None,
    )
    if begin_grid is None:
        raise ValueError(f"{path}: BEGIN_DATAGRID_3D was not found")
    if begin_block + 1 >= begin_grid:
        raise ValueError(f"{path}: data-grid block name is missing")
    if begin_grid + 5 >= len(lines):
        raise ValueError(f"{path}: incomplete data-grid header")

    dimensions_fields = lines[begin_grid + 1].split()
    if len(dimensions_fields) != 3:
        raise ValueError(f"{path}: invalid grid dimensions")
    try:
        dimensions = tuple(int(value) for value in dimensions_fields)
    except ValueError as error:
        raise ValueError(f"{path}: grid dimensions must be integers") from error
    if any(value <= 0 for value in dimensions):
        raise ValueError(f"{path}: grid dimensions must be positive")

    origin = parse_vector(lines[begin_grid + 2], "grid origin", path)
    vectors = tuple(
        parse_vector(lines[begin_grid + offset], "grid vector", path)
        for offset in (3, 4, 5)
    )
    expected_values = math.prod(dimensions)
    data_start = begin_grid + 6

    end_grid = next(
        (
            i
            for i in range(data_start, len(lines))
            if lines[i].strip() == "END_DATAGRID_3D"
        ),
        None,
    )
    if end_grid is None:
        raise ValueError(f"{path}: END_DATAGRID_3D was not found")

    value_fields: list[str] = []
    for line in lines[data_start:end_grid]:
        value_fields.extend(line.split())
    if len(value_fields) != expected_values:
        raise ValueError(
            f"{path}: expected {expected_values} grid values, "
            f"but found {len(value_fields)}"
        )
    try:
        values = [float(value) for value in value_fields]
    except ValueError as error:
        raise ValueError(f"{path}: data grid contains a nonnumeric value") from error

    datagrid_name = lines[begin_grid].strip()[len("BEGIN_DATAGRID_3D") :].lstrip("_")
    return XSFGrid(
        path=path,
        prefix=lines[:begin_block],
        block_name=lines[begin_block + 1].strip(),
        datagrid_name=datagrid_name,
        dimensions=dimensions,  # type: ignore[arg-type]
        origin=origin,
        vectors=vectors,  # type: ignore[arg-type]
        values=values,
    )


def maximum_geometry_difference(a: XSFGrid, b: XSFGrid) -> float:
    numbers_a = (*a.origin, *(value for vector in a.vectors for value in vector))
    numbers_b = (*b.origin, *(value for vector in b.vectors for value in vector))
    return max(abs(x - y) for x, y in zip(numbers_a, numbers_b))


def write_xsf(
    path: Path,
    template: XSFGrid,
    values: list[float],
    operation: str,
    force: bool,
) -> None:
    if path.exists() and not force:
        raise ValueError(f"{path} already exists; use --force to overwrite it")

    with path.open("w", encoding="utf-8") as output:
        output.write("#\n")
        output.write("# Difference between two XSF energy maps (eV)\n")
        output.write(f"# {operation}\n")
        output.write("# Geometry and grid vectors copied from map A\n")
        output.write("#\n")

        prefix = template.prefix
        while prefix and prefix[0].lstrip().startswith("#"):
            prefix = prefix[1:]
        while prefix and not prefix[0].strip():
            prefix = prefix[1:]
        for line in prefix:
            output.write(f"{line}\n")

        output.write("BEGIN_BLOCK_DATAGRID_3D\n")
        output.write("energy_difference\n")
        output.write("BEGIN_DATAGRID_3D_energy_difference\n")
        output.write("{} {} {}\n".format(*template.dimensions))
        output.write("{:.7f} {:.7f} {:.7f}\n".format(*template.origin))
        for vector in template.vectors:
            output.write("  {:.7f}   {:.7f}   {:.7f}\n".format(*vector))
        for value in values:
            output.write(f"  {value:.7f}\n")
        output.write("END_DATAGRID_3D\n")
        output.write("END_BLOCK_DATAGRID_3D\n")


def default_output_path(map_a: Path, map_b: Path) -> Path:
    return map_a.with_name(f"{map_a.stem}_minus_{map_b.stem}.xsf")


def build_parser() -> argparse.ArgumentParser:
    parser = XSFArgumentParser(
        description=(
            "Subtract matching fractional-grid values in two XSF files: "
            "(A + offset-a) - (B + offset-b)."
        )
    )
    parser.add_argument("map_a", type=Path, help="first XSF map (the minuend)")
    parser.add_argument("map_b", type=Path, help="second XSF map (the subtrahend)")
    parser.add_argument("-o", "--output", type=Path, help="output XSF path")
    parser.add_argument(
        "--offset-a",
        type=float,
        default=0.0,
        help="energy in eV added to every value in map A (default: 0)",
    )
    parser.add_argument(
        "--offset-b",
        type=float,
        default=0.0,
        help="energy in eV added to every value in map B (default: 0)",
    )
    parser.add_argument(
        "--align-minima",
        action="store_true",
        help="put the maps on top of each other by shifting each minimum to 0 eV",
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
        map_a = read_xsf(args.map_a)
        map_b = read_xsf(args.map_b)

        if map_a.dimensions != map_b.dimensions:
            raise ValueError(
                "grid dimensions differ: "
                f"{map_a.path} has {map_a.dimensions}, "
                f"{map_b.path} has {map_b.dimensions}"
            )

        geometry_difference = maximum_geometry_difference(map_a, map_b)
        if geometry_difference > 1e-7:
            print(
                "Warning: origins or grid vectors differ "
                f"(maximum difference {geometry_difference:.7g} A).",
                file=sys.stderr,
            )
            print(
                "         Values will be matched by fractional-grid index; "
                "the output uses map A's geometry.",
                file=sys.stderr,
            )

        minimum_a = min(map_a.values)
        minimum_b = min(map_b.values)
        if args.align_minima:
            if args.offset_a != 0.0 or args.offset_b != 0.0:
                raise ValueError(
                    "--align-minima cannot be combined with --offset-a or --offset-b"
                )
            offset_a = -minimum_a
            offset_b = -minimum_b
            operation = (
                f"({map_a.path} - min {minimum_a:.10g}) - "
                f"({map_b.path} - min {minimum_b:.10g})"
            )
        else:
            offset_a = args.offset_a
            offset_b = args.offset_b
            operation = (
                f"({map_a.path} + {offset_a:.10g}) - "
                f"({map_b.path} + {offset_b:.10g})"
            )

        difference = [
            (value_a + offset_a) - (value_b + offset_b)
            for value_a, value_b in zip(map_a.values, map_b.values)
        ]
        output_path = args.output or default_output_path(args.map_a, args.map_b)
        write_xsf(output_path, map_a, difference, operation, args.force)

        print(f"Grid:       {' x '.join(map(str, map_a.dimensions))}")
        print(f"Map A min:  {minimum_a:.7f} eV")
        print(f"Map B min:  {minimum_b:.7f} eV")
        print(f"Offset A:   {offset_a:+.7f} eV")
        print(f"Offset B:   {offset_b:+.7f} eV")
        print(f"Result:     {min(difference):.7f} to {max(difference):.7f} eV")
        print(f"Written:    {output_path}")
        return 0
    except (OSError, ValueError) as error:
        print_options()
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
