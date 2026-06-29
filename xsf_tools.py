"""Reusable helpers for cutting and subtracting XSF 3-D data grids."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


Bounds = tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class CutStats:
    shape: tuple[int, int, int]
    selected_points: int
    total_points: int
    coordinate_mode: str
    output_min: float
    output_max: float


@dataclass(frozen=True)
class SubtractStats:
    dimensions: tuple[int, int, int]
    values: int
    map_a_min: float
    map_b_min: float
    offset_a: float
    offset_b: float
    result_min: float
    result_max: float


@dataclass
class XSFCutGrid:
    source_name: str
    lines: list[str]
    shape: tuple[int, int, int]
    origin: np.ndarray
    vectors: np.ndarray
    data: np.ndarray
    data_start: int
    data_end: int


@dataclass
class XSFMap:
    source_name: str
    prefix: list[str]
    dimensions: tuple[int, int, int]
    origin: tuple[float, float, float]
    vectors: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    values: list[float]


def _normalise_bounds(bounds: Sequence[Sequence[float]]) -> Bounds:
    if len(bounds) != 3:
        raise ValueError("bounds must contain exactly three coordinate ranges")

    normalised: list[tuple[float, float]] = []
    for pair in bounds:
        if len(pair) != 2:
            raise ValueError("each bound must contain a minimum and maximum")
        lower = float(pair[0])
        upper = float(pair[1])
        if lower > upper:
            raise ValueError(f"invalid bound ({lower}, {upper}): minimum > maximum")
        normalised.append((lower, upper))

    return normalised[0], normalised[1], normalised[2]


def parse_cut_grid_text(input_text: str, source_name: str = "uploaded.xsf") -> XSFCutGrid:
    """Read the first 3-D DATAGRID block for the region-cut workflow."""
    lines = input_text.splitlines(keepends=True)
    begin = next(
        (i for i, line in enumerate(lines) if "BEGIN_DATAGRID_3D" in line),
        None,
    )
    if begin is None:
        raise ValueError(f"{source_name}: no BEGIN_DATAGRID_3D section found")

    dimensions_line = None
    dimensions = None
    for i in range(begin + 1, len(lines)):
        if "END_DATAGRID_3D" in lines[i]:
            break
        parts = lines[i].split()
        if len(parts) != 3:
            continue
        try:
            candidate = tuple(int(part) for part in parts)
        except ValueError:
            continue
        if all(value > 0 for value in candidate):
            dimensions_line = i
            dimensions = candidate
            break

    if dimensions_line is None or dimensions is None:
        raise ValueError(f"{source_name}: DATAGRID dimensions not found")

    nx, ny, nz = dimensions
    data_start = dimensions_line + 5
    if data_start >= len(lines):
        raise ValueError(f"{source_name}: incomplete DATAGRID header")

    try:
        origin = np.asarray(lines[dimensions_line + 1].split(), dtype=float)
        vectors = np.asarray(
            [
                lines[dimensions_line + 2].split(),
                lines[dimensions_line + 3].split(),
                lines[dimensions_line + 4].split(),
            ],
            dtype=float,
        )
    except ValueError as error:
        raise ValueError(f"{source_name}: invalid DATAGRID origin or vectors") from error

    if origin.shape != (3,) or vectors.shape != (3, 3):
        raise ValueError(f"{source_name}: DATAGRID origin and vectors must have 3 components")

    end = next(
        (
            i
            for i in range(data_start, len(lines))
            if "END_DATAGRID_3D" in lines[i]
        ),
        None,
    )
    if end is None:
        raise ValueError(f"{source_name}: END_DATAGRID_3D not found")

    values = np.fromstring(" ".join(lines[data_start:end]), sep=" ")
    expected = nx * ny * nz
    if values.size != expected:
        raise ValueError(
            f"{source_name}: expected {expected} DATAGRID values, found {values.size}"
        )

    data = values.reshape((nx, ny, nz), order="F")
    return XSFCutGrid(
        source_name=source_name,
        lines=lines,
        shape=(nx, ny, nz),
        origin=origin,
        vectors=vectors,
        data=data,
        data_start=data_start,
        data_end=end,
    )


def make_region_mask(
    shape: tuple[int, int, int],
    origin: np.ndarray,
    vectors: np.ndarray,
    bounds: Sequence[Sequence[float]],
    coordinate_mode: str,
) -> np.ndarray:
    """Return a mask in either Cartesian or DATAGRID fractional coordinates."""
    nx, ny, nz = shape
    checked_bounds = _normalise_bounds(bounds)

    # XSF grid vectors connect the first and last grid points, so N points
    # contain N-1 intervals and include fractional coordinates 0 and 1.
    u = np.linspace(0.0, 1.0, nx)[:, None, None]
    v = np.linspace(0.0, 1.0, ny)[None, :, None]
    w = np.linspace(0.0, 1.0, nz)[None, None, :]

    mode = coordinate_mode.lower()
    if mode == "fractional":
        coordinates = (u, v, w)
    elif mode == "cartesian":
        x = origin[0] + u * vectors[0, 0] + v * vectors[1, 0] + w * vectors[2, 0]
        y = origin[1] + u * vectors[0, 1] + v * vectors[1, 1] + w * vectors[2, 1]
        z = origin[2] + u * vectors[0, 2] + v * vectors[1, 2] + w * vectors[2, 2]
        coordinates = (x, y, z)
    else:
        raise ValueError(
            f"unknown coordinate_mode {coordinate_mode!r}; use 'cartesian' or 'fractional'"
        )

    inside = np.ones(shape, dtype=bool)
    for coordinate, (lower, upper) in zip(coordinates, checked_bounds):
        inside &= (coordinate >= lower) & (coordinate <= upper)

    return inside


def write_cut_grid_text(grid: XSFCutGrid, masked_data: np.ndarray) -> str:
    """Replace only the values of the parsed DATAGRID block."""
    flat = masked_data.ravel(order="F")
    value_lines = []
    values_per_line = 6
    for start in range(0, flat.size, values_per_line):
        chunk = flat[start : start + values_per_line]
        value_lines.append("  " + "  ".join(f"{value:.7f}" for value in chunk) + "\n")

    output = grid.lines[: grid.data_start] + value_lines + grid.lines[grid.data_end :]
    return "".join(output)


def cut_xsf_text(
    input_text: str,
    bounds: Sequence[Sequence[float]],
    coordinate_mode: str = "cartesian",
    outside_value: float = 0.0,
    test_value: float | None = None,
    source_name: str = "uploaded.xsf",
) -> tuple[str, CutStats]:
    """Cut an XSF data grid to a region and return the output text plus stats."""
    grid = parse_cut_grid_text(input_text, source_name=source_name)
    inside = make_region_mask(
        grid.shape,
        grid.origin,
        grid.vectors,
        bounds,
        coordinate_mode,
    )

    masked = np.full(grid.shape, float(outside_value), dtype=float)
    if test_value is None:
        masked[inside] = grid.data[inside]
    else:
        masked[inside] = float(test_value)

    result_text = write_cut_grid_text(grid, masked)
    stats = CutStats(
        shape=grid.shape,
        selected_points=int(np.count_nonzero(inside)),
        total_points=int(np.prod(grid.shape)),
        coordinate_mode=coordinate_mode.lower(),
        output_min=float(np.min(masked)),
        output_max=float(np.max(masked)),
    )
    return result_text, stats


def parse_vector(line: str, description: str, source_name: str) -> tuple[float, float, float]:
    fields = line.split()
    if len(fields) != 3:
        raise ValueError(f"{source_name}: invalid {description}: {line!r}")
    try:
        return tuple(float(value) for value in fields)  # type: ignore[return-value]
    except ValueError as error:
        raise ValueError(f"{source_name}: nonnumeric {description}: {line!r}") from error


def read_xsf_map_text(input_text: str, source_name: str = "uploaded.xsf") -> XSFMap:
    """Read an XSF map for values-only subtraction."""
    lines = input_text.splitlines()
    begin_block = next(
        (i for i, line in enumerate(lines) if line.strip() == "BEGIN_BLOCK_DATAGRID_3D"),
        None,
    )
    if begin_block is None:
        raise ValueError(f"{source_name}: BEGIN_BLOCK_DATAGRID_3D was not found")

    begin_grid = next(
        (
            i
            for i in range(begin_block + 1, len(lines))
            if lines[i].strip().startswith("BEGIN_DATAGRID_3D")
        ),
        None,
    )
    if begin_grid is None:
        raise ValueError(f"{source_name}: BEGIN_DATAGRID_3D was not found")
    if begin_grid + 5 >= len(lines):
        raise ValueError(f"{source_name}: incomplete data-grid header")

    dimension_fields = lines[begin_grid + 1].split()
    if len(dimension_fields) != 3:
        raise ValueError(f"{source_name}: invalid grid dimensions")
    try:
        dimensions = tuple(int(value) for value in dimension_fields)
    except ValueError as error:
        raise ValueError(f"{source_name}: grid dimensions must be integers") from error
    if any(value <= 0 for value in dimensions):
        raise ValueError(f"{source_name}: grid dimensions must be positive")

    origin = parse_vector(lines[begin_grid + 2], "grid origin", source_name)
    vectors = tuple(
        parse_vector(lines[begin_grid + offset], "grid vector", source_name)
        for offset in (3, 4, 5)
    )

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
        raise ValueError(f"{source_name}: END_DATAGRID_3D was not found")

    value_fields: list[str] = []
    for line in lines[data_start:end_grid]:
        value_fields.extend(line.split())

    expected_values = math.prod(dimensions)
    if len(value_fields) != expected_values:
        raise ValueError(
            f"{source_name}: grid header expects {expected_values} values, "
            f"but the data block contains {len(value_fields)}"
        )

    try:
        values = [float(value) for value in value_fields]
    except ValueError as error:
        raise ValueError(f"{source_name}: data grid contains a nonnumeric value") from error

    return XSFMap(
        source_name=source_name,
        prefix=lines[:begin_block],
        dimensions=dimensions,  # type: ignore[arg-type]
        origin=origin,
        vectors=vectors,  # type: ignore[arg-type]
        values=values,
    )


def write_subtract_xsf_text(template: XSFMap, values: Sequence[float], operation: str) -> str:
    lines = [
        "#\n",
        "# Difference between two XSF energy maps (eV)\n",
        "# Box/origin/vector compatibility was intentionally not checked\n",
        f"# {operation}\n",
        "# Output structure and grid header copied from map A\n",
        "#\n",
    ]

    prefix = template.prefix
    while prefix and prefix[0].lstrip().startswith("#"):
        prefix = prefix[1:]
    while prefix and not prefix[0].strip():
        prefix = prefix[1:]
    lines.extend(f"{line}\n" for line in prefix)

    lines.append("BEGIN_BLOCK_DATAGRID_3D\n")
    lines.append("energy_difference_values_only\n")
    lines.append("BEGIN_DATAGRID_3D_energy_difference_values_only\n")
    lines.append("{} {} {}\n".format(*template.dimensions))
    lines.append("{:.7f} {:.7f} {:.7f}\n".format(*template.origin))
    for vector in template.vectors:
        lines.append("  {:.7f}   {:.7f}   {:.7f}\n".format(*vector))
    for value in values:
        lines.append(f"  {value:.7f}\n")
    lines.append("END_DATAGRID_3D\n")
    lines.append("END_BLOCK_DATAGRID_3D\n")
    return "".join(lines)


def subtract_xsf_text(
    map_a_text: str,
    map_b_text: str,
    offset_a: float = 0.0,
    offset_b: float = 0.0,
    align_minima: bool = False,
    map_a_name: str = "map A",
    map_b_name: str = "map B",
) -> tuple[str, SubtractStats]:
    """Subtract two XSF map value arrays without checking cell compatibility."""
    map_a = read_xsf_map_text(map_a_text, source_name=map_a_name)
    map_b = read_xsf_map_text(map_b_text, source_name=map_b_name)

    if len(map_a.values) != len(map_b.values):
        raise ValueError(
            "maps do not have the same number of values: "
            f"{map_a.source_name} has {len(map_a.values)}, "
            f"{map_b.source_name} has {len(map_b.values)}"
        )

    minimum_a = min(map_a.values)
    minimum_b = min(map_b.values)
    if align_minima:
        if offset_a != 0.0 or offset_b != 0.0:
            raise ValueError("--align-minima cannot be combined with --offset-a or --offset-b")
        applied_offset_a = -minimum_a
        applied_offset_b = -minimum_b
        operation = (
            f"({map_a.source_name} - min {minimum_a:.10g}) - "
            f"({map_b.source_name} - min {minimum_b:.10g})"
        )
    else:
        applied_offset_a = float(offset_a)
        applied_offset_b = float(offset_b)
        operation = (
            f"({map_a.source_name} + {applied_offset_a:.10g}) - "
            f"({map_b.source_name} + {applied_offset_b:.10g})"
        )

    difference = [
        (value_a + applied_offset_a) - (value_b + applied_offset_b)
        for value_a, value_b in zip(map_a.values, map_b.values)
    ]
    result_text = write_subtract_xsf_text(map_a, difference, operation)
    stats = SubtractStats(
        dimensions=map_a.dimensions,
        values=len(difference),
        map_a_min=minimum_a,
        map_b_min=minimum_b,
        offset_a=applied_offset_a,
        offset_b=applied_offset_b,
        result_min=min(difference),
        result_max=max(difference),
    )
    return result_text, stats


def default_subtract_output_path(map_a: Path, map_b: Path) -> Path:
    return map_a.with_name(f"{map_a.stem}_minus_{map_b.stem}_values.xsf")


def subtract_xsf_file_paths(
    map_a_path: Path,
    map_b_path: Path,
    output_path: Path | None = None,
    offset_a: float = 0.0,
    offset_b: float = 0.0,
    align_minima: bool = False,
    force: bool = False,
) -> tuple[Path, SubtractStats]:
    """File-path wrapper used by the command-line subtraction scripts."""
    target = output_path or default_subtract_output_path(map_a_path, map_b_path)
    if target.exists() and not force:
        raise ValueError(f"{target} already exists; use --force to overwrite it")

    try:
        map_a_text = map_a_path.read_text(encoding="utf-8")
        map_b_text = map_b_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read input XSF file: {error}") from error

    result_text, stats = subtract_xsf_text(
        map_a_text,
        map_b_text,
        offset_a=offset_a,
        offset_b=offset_b,
        align_minima=align_minima,
        map_a_name=str(map_a_path),
        map_b_name=str(map_b_path),
    )

    try:
        target.write_text(result_text, encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot write {target}: {error}") from error

    return target, stats
