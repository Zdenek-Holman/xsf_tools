#!/usr/bin/env python3
"""Export one or more 2-D slices of an XSF energy grid as TIFF images."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PIL import Image

from xsf_tools import parse_cut_grid_text


AXIS_TO_NUMBER = {"x": 0, "y": 1, "z": 2}
PLANE_AXES = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}
BIT_DEPTHS = {16, 32}
SCALING_MODES = {"shared", "per-slice"}


@dataclass(frozen=True)
class SliceResult:
    axis: str
    index: int
    geometry: str
    bit_depth: int
    scaling: str
    image_shape: tuple[int, int]
    energy_min: float
    energy_max: float
    output_path: Path


@dataclass(frozen=True)
class SliceImageResult:
    axis: str
    index: int
    geometry: str
    bit_depth: int
    scaling: str
    image_shape: tuple[int, int]
    energy_min: float
    energy_max: float
    scale_min: float
    scale_max: float
    image_data: np.ndarray


@dataclass(frozen=True)
class SliceExportResult:
    axis: str
    indices: tuple[int, ...]
    geometry: str
    bit_depth: int
    scaling: str
    image_shapes: tuple[tuple[int, int], ...]
    energy_min: float
    energy_max: float
    images: tuple[SliceImageResult, ...]
    filename: str
    mime_type: str


def print_options(file=sys.stderr) -> None:
    print(
        "Create 16-bit integer or 32-bit float grayscale TIFF slices from an XSF map.\n"
        "\n"
        "Examples:\n"
        "python3 xsf_slice_to_tiff.py map.xsf --index 45\n"
        "python3 xsf_slice_to_tiff.py map.xsf --indices 0,20,45,89 --bit-depth 16\n"
        "python3 xsf_slice_to_tiff.py map.xsf --count 10 --geometry real\n"
        "python3 xsf_slice_to_tiff.py map.xsf --count 5 --scaling per-slice -o cuts.zip\n",
        file=file,
    )


class SliceArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print_options()
        self.exit(2, f"Error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = SliceArgumentParser(
        description="Write one TIFF slice or a ZIP containing multiple TIFF slices from an XSF grid."
    )
    parser.add_argument("input_xsf", type=Path, help="input XSF energy map")
    parser.add_argument("-o", "--output", type=Path, help="output TIFF or ZIP path")
    parser.add_argument(
        "--axis",
        choices=("x", "y", "z"),
        default="z",
        help="axis perpendicular to the cut plane (default: z)",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--index",
        type=int,
        help="one slice index (default: middle slice)",
    )
    selection.add_argument(
        "--indices",
        help="comma-separated exact slice indices, for example 0,20,45,89",
    )
    selection.add_argument(
        "--count",
        type=int,
        help="number of equidistant slices spanning the complete selected axis",
    )
    parser.add_argument(
        "--bit-depth",
        type=int,
        choices=(16, 32),
        default=32,
        help="TIFF pixel depth: uint16 or normalized float32 (default: 32)",
    )
    parser.add_argument(
        "--scaling",
        choices=("shared", "per-slice"),
        default="shared",
        help="use one contrast range for all slices or scale each separately (default: shared)",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="make low energy bright and high energy dark",
    )
    parser.add_argument(
        "--geometry",
        choices=("grid", "real"),
        default="grid",
        help="render in grid-index space or projected real space (default: grid)",
    )
    parser.add_argument(
        "--pixels-per-angstrom",
        type=float,
        help="real-space output resolution; default follows the XSF grid spacing",
    )
    parser.add_argument(
        "--background",
        choices=("black", "white"),
        default="black",
        help="background outside the real-space cell (default: black)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the output file if it already exists",
    )
    return parser


def parse_slice_indices(value: str) -> list[int]:
    """Parse and validate a comma-separated list of exact slice indices."""
    if not value.strip():
        raise ValueError("the exact index list is empty")

    indices: list[int] = []
    for position, token in enumerate(value.split(","), start=1):
        token = token.strip()
        if not token:
            raise ValueError(f"index entry {position} is empty")
        try:
            index = int(token)
        except ValueError as error:
            raise ValueError(f"invalid slice index {token!r}; use comma-separated integers") from error
        indices.append(index)

    if len(set(indices)) != len(indices):
        raise ValueError("slice indices must not contain duplicates")
    return indices


def select_slice_indices(
    axis_size: int,
    *,
    index: int | None = None,
    indices: list[int] | tuple[int, ...] | None = None,
    count: int | None = None,
) -> list[int]:
    """Resolve exact, equidistant, or default-middle slice selection."""
    supplied = sum(value is not None for value in (index, indices, count))
    if supplied > 1:
        raise ValueError("choose only one of index, indices, or count")
    if axis_size < 1:
        raise ValueError("the selected grid axis contains no slices")

    if indices is not None:
        selected = [int(value) for value in indices]
        if not selected:
            raise ValueError("the exact index list is empty")
        if len(set(selected)) != len(selected):
            raise ValueError("slice indices must not contain duplicates")
    elif count is not None:
        if count < 1:
            raise ValueError("slice count must be at least 1")
        if count > axis_size:
            raise ValueError(
                f"slice count {count} exceeds the {axis_size} available positions"
            )
        if count == 1:
            selected = [axis_size // 2]
        else:
            selected = np.rint(np.linspace(0, axis_size - 1, count)).astype(int).tolist()
    elif index is not None:
        selected = [index]
    else:
        selected = [axis_size // 2]

    for selected_index in selected:
        if selected_index < 0 or selected_index >= axis_size:
            raise ValueError(
                f"index {selected_index} is outside the selected axis; "
                f"valid range is 0..{axis_size - 1}"
            )
    return selected


def slice_filename(stem: str, axis: str, index: int, geometry: str) -> str:
    suffix = f"{axis}{index:03d}"
    if geometry == "real":
        suffix += "_real"
    return f"{stem}_{suffix}.tiff"


def default_output_path(
    input_xsf: Path,
    axis: str,
    index: int,
    geometry: str,
) -> Path:
    return input_xsf.with_name(slice_filename(input_xsf.stem, axis, index, geometry))


def default_archive_path(input_xsf: Path, axis: str, geometry: str) -> Path:
    suffix = f"{axis}_slices"
    if geometry == "real":
        suffix += "_real"
    return input_xsf.with_name(f"{input_xsf.stem}_{suffix}.zip")


def extract_slice(data: np.ndarray, axis: str, index: int) -> np.ndarray:
    axis_number = AXIS_TO_NUMBER[axis]
    if axis_number == 0:
        slice_2d = data[index, :, :]
    elif axis_number == 1:
        slice_2d = data[:, index, :]
    else:
        slice_2d = data[:, :, index]

    # NumPy images use row, column. Transpose so the first remaining grid axis
    # goes left-to-right and the second goes top-to-bottom.
    return np.asarray(slice_2d, dtype=float).T


def extract_slice_plane(data: np.ndarray, axis: str, index: int) -> np.ndarray:
    """Return a 2-D slice with dimensions matching the two in-plane grid axes."""
    axis_number = AXIS_TO_NUMBER[axis]
    if axis_number == 0:
        return np.asarray(data[index, :, :], dtype=float)
    if axis_number == 1:
        return np.asarray(data[:, index, :], dtype=float)
    return np.asarray(data[:, :, index], dtype=float)


def finite_limits(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("slice contains no finite energy values")
    return float(np.min(finite)), float(np.max(finite))


def scale_with_limits(
    values: np.ndarray,
    energy_min: float,
    energy_max: float,
    invert: bool,
    bit_depth: int = 16,
) -> np.ndarray:
    """Scale energies to uint16 or normalized float32 image samples."""
    if bit_depth not in BIT_DEPTHS:
        raise ValueError("bit depth must be 16 or 32")

    if energy_max > energy_min:
        scaled = (values - energy_min) / (energy_max - energy_min)
    else:
        scaled = np.zeros_like(values, dtype=float)

    if invert:
        scaled = 1.0 - scaled
    scaled = np.clip(scaled, 0.0, 1.0)

    if bit_depth == 16:
        return np.rint(scaled * 65535.0).astype(np.uint16)
    return scaled.astype(np.float32)


def scale_to_uint16(slice_2d: np.ndarray, invert: bool) -> tuple[np.ndarray, float, float]:
    """Backward-compatible helper for scaling one slice to uint16."""
    energy_min, energy_max = finite_limits(slice_2d)
    return (
        scale_with_limits(slice_2d, energy_min, energy_max, invert, bit_depth=16),
        energy_min,
        energy_max,
    )


def project_plane_vectors(
    vector_u: np.ndarray,
    vector_v: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Project two 3-D in-plane vectors into a local 2-D Cartesian plane."""
    length_u = float(np.linalg.norm(vector_u))
    if length_u <= 0.0:
        raise ValueError("cannot render real-space slice: first in-plane vector has zero length")

    e_u = vector_u / length_u
    v_x = float(np.dot(vector_v, e_u))
    v_perp = vector_v - v_x * e_u
    v_y = float(np.linalg.norm(v_perp))
    if v_y <= 1e-12:
        raise ValueError("cannot render real-space slice: in-plane vectors are parallel")

    return np.array([length_u, 0.0], dtype=float), np.array([v_x, v_y], dtype=float)


def default_pixels_per_angstrom(
    plane_shape: tuple[int, int],
    vector_u_2d: np.ndarray,
    vector_v_2d: np.ndarray,
) -> float:
    length_u = float(np.linalg.norm(vector_u_2d))
    length_v = float(np.linalg.norm(vector_v_2d))
    samples_u, samples_v = plane_shape
    candidates = []
    if length_u > 0.0 and samples_u > 1:
        candidates.append((samples_u - 1) / length_u)
    if length_v > 0.0 and samples_v > 1:
        candidates.append((samples_v - 1) / length_v)
    if not candidates:
        raise ValueError("cannot choose real-space resolution for a 1x1 slice")
    return max(candidates)


def bilinear_sample(
    plane: np.ndarray,
    u_fraction: np.ndarray,
    v_fraction: np.ndarray,
) -> np.ndarray:
    """Sample plane[u, v] at fractional coordinates in [0, 1]."""
    size_u, size_v = plane.shape
    u_index = np.clip(u_fraction, 0.0, 1.0) * (size_u - 1)
    v_index = np.clip(v_fraction, 0.0, 1.0) * (size_v - 1)

    u0 = np.floor(u_index).astype(np.int64)
    v0 = np.floor(v_index).astype(np.int64)
    u1 = np.clip(u0 + 1, 0, size_u - 1)
    v1 = np.clip(v0 + 1, 0, size_v - 1)
    u0 = np.clip(u0, 0, size_u - 1)
    v0 = np.clip(v0, 0, size_v - 1)

    du = u_index - u0
    dv = v_index - v0
    return (
        plane[u0, v0] * (1.0 - du) * (1.0 - dv)
        + plane[u1, v0] * du * (1.0 - dv)
        + plane[u0, v1] * (1.0 - du) * dv
        + plane[u1, v1] * du * dv
    )


def real_space_samples(
    plane: np.ndarray,
    vector_u: np.ndarray,
    vector_v: np.ndarray,
    pixels_per_angstrom: float | None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Interpolate one oblique plane onto a rectangular real-space canvas."""
    vector_u_2d, vector_v_2d = project_plane_vectors(vector_u, vector_v)
    if pixels_per_angstrom is None:
        pixels_per_angstrom = default_pixels_per_angstrom(
            plane.shape, vector_u_2d, vector_v_2d
        )
    if pixels_per_angstrom <= 0.0:
        raise ValueError("--pixels-per-angstrom must be greater than zero")

    corners = np.array(
        [[0.0, 0.0], vector_u_2d, vector_v_2d, vector_u_2d + vector_v_2d],
        dtype=float,
    )
    lower = corners.min(axis=0)
    upper = corners.max(axis=0)
    width = int(np.ceil((upper[0] - lower[0]) * pixels_per_angstrom)) + 1
    height = int(np.ceil((upper[1] - lower[1]) * pixels_per_angstrom)) + 1
    if width <= 0 or height <= 0:
        raise ValueError("real-space slice has an invalid projected size")

    columns = lower[0] + np.arange(width, dtype=float) / pixels_per_angstrom
    rows = upper[1] - np.arange(height, dtype=float) / pixels_per_angstrom
    x, y = np.meshgrid(columns, rows)

    basis = np.column_stack([vector_u_2d, vector_v_2d])
    fractions = np.linalg.inv(basis) @ np.stack([x.ravel(), y.ravel()], axis=0)
    u_fraction = fractions[0].reshape((height, width))
    v_fraction = fractions[1].reshape((height, width))
    tolerance = 1e-9
    inside = (
        (u_fraction >= -tolerance)
        & (u_fraction <= 1.0 + tolerance)
        & (v_fraction >= -tolerance)
        & (v_fraction <= 1.0 + tolerance)
    )
    return bilinear_sample(plane, u_fraction, v_fraction), inside, pixels_per_angstrom


def render_real_space_slice(
    plane: np.ndarray,
    vector_u: np.ndarray,
    vector_v: np.ndarray,
    pixels_per_angstrom: float | None,
    invert: bool,
    background: str,
    bit_depth: int = 16,
    energy_limits: tuple[float, float] | None = None,
) -> tuple[np.ndarray, float, float, float]:
    """Render a real-space plane; defaults retain the former uint16 behavior."""
    energy_min, energy_max = finite_limits(plane)
    scale_min, scale_max = energy_limits or (energy_min, energy_max)
    sampled, inside, final_resolution = real_space_samples(
        plane, vector_u, vector_v, pixels_per_angstrom
    )
    scaled = scale_with_limits(sampled, scale_min, scale_max, invert, bit_depth)
    if bit_depth == 16:
        background_value: int | float = 0 if background == "black" else 65535
        image_data = np.full(scaled.shape, background_value, dtype=np.uint16)
    else:
        background_value = 0.0 if background == "black" else 1.0
        image_data = np.full(scaled.shape, background_value, dtype=np.float32)
    image_data[inside] = scaled[inside]
    return image_data, energy_min, energy_max, final_resolution


def _validate_render_options(
    axis: str,
    geometry: str,
    background: str,
    bit_depth: int,
    scaling: str,
) -> None:
    if axis not in AXIS_TO_NUMBER:
        raise ValueError(f"unknown axis {axis!r}; use 'x', 'y', or 'z'")
    if geometry not in {"grid", "real"}:
        raise ValueError(f"unknown geometry {geometry!r}; use 'grid' or 'real'")
    if background not in {"black", "white"}:
        raise ValueError(f"unknown background {background!r}; use 'black' or 'white'")
    if bit_depth not in BIT_DEPTHS:
        raise ValueError("bit depth must be 16 or 32")
    if scaling not in SCALING_MODES:
        raise ValueError("scaling must be 'shared' or 'per-slice'")


def _render_parsed_slice(
    grid,
    *,
    axis: str,
    index: int,
    invert: bool,
    geometry: str,
    pixels_per_angstrom: float | None,
    background: str,
    bit_depth: int,
    scaling: str,
    scale_limits: tuple[float, float],
) -> SliceImageResult:
    plane = extract_slice_plane(grid.data, axis, index)
    energy_min, energy_max = finite_limits(plane)
    scale_min, scale_max = scale_limits

    if geometry == "grid":
        values = extract_slice(grid.data, axis, index)
        image_data = scale_with_limits(
            values, scale_min, scale_max, invert, bit_depth
        )
    else:
        plane_axis_u, plane_axis_v = PLANE_AXES[axis]
        image_data, _, _, _ = render_real_space_slice(
            plane,
            grid.vectors[plane_axis_u],
            grid.vectors[plane_axis_v],
            pixels_per_angstrom,
            invert,
            background,
            bit_depth=bit_depth,
            energy_limits=scale_limits,
        )

    return SliceImageResult(
        axis=axis,
        index=index,
        geometry=geometry,
        bit_depth=bit_depth,
        scaling=scaling,
        image_shape=(int(image_data.shape[1]), int(image_data.shape[0])),
        energy_min=energy_min,
        energy_max=energy_max,
        scale_min=scale_min,
        scale_max=scale_max,
        image_data=image_data,
    )


def render_slice_images(
    input_text: str,
    source_name: str = "uploaded.xsf",
    axis: str = "z",
    index: int | None = None,
    indices: list[int] | tuple[int, ...] | None = None,
    count: int | None = None,
    invert: bool = False,
    geometry: str = "grid",
    pixels_per_angstrom: float | None = None,
    background: str = "black",
    bit_depth: int = 32,
    scaling: str = "shared",
) -> tuple[SliceImageResult, ...]:
    """Render selected slices with shared or independent contrast limits."""
    _validate_render_options(axis, geometry, background, bit_depth, scaling)
    grid = parse_cut_grid_text(input_text, source_name=source_name)
    selected = select_slice_indices(
        grid.shape[AXIS_TO_NUMBER[axis]],
        index=index,
        indices=indices,
        count=count,
    )

    local_limits = [finite_limits(extract_slice_plane(grid.data, axis, i)) for i in selected]
    shared_limits = (
        min(limits[0] for limits in local_limits),
        max(limits[1] for limits in local_limits),
    )
    return tuple(
        _render_parsed_slice(
            grid,
            axis=axis,
            index=selected_index,
            invert=invert,
            geometry=geometry,
            pixels_per_angstrom=pixels_per_angstrom,
            background=background,
            bit_depth=bit_depth,
            scaling=scaling,
            scale_limits=(
                shared_limits if scaling == "shared" else local_limits[position]
            ),
        )
        for position, selected_index in enumerate(selected)
    )


def render_slice_image(
    input_text: str,
    source_name: str,
    axis: str,
    index: int | None,
    invert: bool,
    geometry: str,
    pixels_per_angstrom: float | None,
    background: str,
    bit_depth: int = 32,
) -> SliceImageResult:
    """Backward-compatible single-slice renderer, now float32 by default."""
    return render_slice_images(
        input_text,
        source_name=source_name,
        axis=axis,
        index=index,
        invert=invert,
        geometry=geometry,
        pixels_per_angstrom=pixels_per_angstrom,
        background=background,
        bit_depth=bit_depth,
        scaling="shared",
    )[0]


def image_to_tiff_bytes(image_data: np.ndarray) -> bytes:
    buffer = BytesIO()
    Image.fromarray(image_data).save(buffer, format="TIFF")
    return buffer.getvalue()


def export_xsf_slices_to_bytes(
    input_text: str,
    source_name: str = "uploaded.xsf",
    filename_stem: str = "energy_grid",
    axis: str = "z",
    index: int | None = None,
    indices: list[int] | tuple[int, ...] | None = None,
    count: int | None = None,
    invert: bool = False,
    geometry: str = "grid",
    pixels_per_angstrom: float | None = None,
    background: str = "black",
    bit_depth: int = 32,
    scaling: str = "shared",
) -> tuple[bytes, SliceExportResult]:
    """Return one TIFF or a ZIP of TIFFs plus export statistics."""
    images = render_slice_images(
        input_text,
        source_name=source_name,
        axis=axis,
        index=index,
        indices=indices,
        count=count,
        invert=invert,
        geometry=geometry,
        pixels_per_angstrom=pixels_per_angstrom,
        background=background,
        bit_depth=bit_depth,
        scaling=scaling,
    )
    stem = Path(filename_stem).stem or "energy_grid"
    if len(images) == 1:
        filename = slice_filename(stem, axis, images[0].index, geometry)
        output_bytes = image_to_tiff_bytes(images[0].image_data)
        mime_type = "image/tiff"
    else:
        archive_suffix = f"{axis}_slices"
        if geometry == "real":
            archive_suffix += "_real"
        filename = f"{stem}_{archive_suffix}.zip"
        buffer = BytesIO()
        with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
            for image in images:
                archive.writestr(
                    slice_filename(stem, axis, image.index, geometry),
                    image_to_tiff_bytes(image.image_data),
                )
        output_bytes = buffer.getvalue()
        mime_type = "application/zip"

    result = SliceExportResult(
        axis=axis,
        indices=tuple(image.index for image in images),
        geometry=geometry,
        bit_depth=bit_depth,
        scaling=scaling,
        image_shapes=tuple(image.image_shape for image in images),
        energy_min=min(image.energy_min for image in images),
        energy_max=max(image.energy_max for image in images),
        images=images,
        filename=filename,
        mime_type=mime_type,
    )
    return output_bytes, result


def slice_xsf_text_to_tiff_bytes(
    input_text: str,
    source_name: str = "uploaded.xsf",
    axis: str = "z",
    index: int | None = None,
    invert: bool = False,
    geometry: str = "grid",
    pixels_per_angstrom: float | None = None,
    background: str = "black",
    bit_depth: int = 32,
) -> tuple[bytes, SliceImageResult]:
    """Compatibility wrapper that always exports one TIFF."""
    output_bytes, export = export_xsf_slices_to_bytes(
        input_text,
        source_name=source_name,
        filename_stem=Path(source_name).stem,
        axis=axis,
        index=index,
        invert=invert,
        geometry=geometry,
        pixels_per_angstrom=pixels_per_angstrom,
        background=background,
        bit_depth=bit_depth,
        scaling="shared",
    )
    return output_bytes, export.images[0]


def write_slice_tiff(
    input_xsf: Path,
    output_path: Path | None,
    axis: str,
    index: int | None,
    invert: bool,
    geometry: str,
    pixels_per_angstrom: float | None,
    background: str,
    force: bool,
    bit_depth: int = 32,
) -> SliceResult:
    """Compatibility wrapper for writing one selected TIFF."""
    text = input_xsf.read_text(encoding="utf-8")
    output_bytes, export = export_xsf_slices_to_bytes(
        text,
        source_name=str(input_xsf),
        filename_stem=input_xsf.stem,
        axis=axis,
        index=index,
        invert=invert,
        geometry=geometry,
        pixels_per_angstrom=pixels_per_angstrom,
        background=background,
        bit_depth=bit_depth,
    )
    image = export.images[0]
    final_path = output_path or default_output_path(input_xsf, axis, image.index, geometry)
    if final_path.exists() and not force:
        raise ValueError(f"{final_path} already exists; use --force to overwrite it")
    final_path.write_bytes(output_bytes)
    return SliceResult(
        axis=axis,
        index=image.index,
        geometry=geometry,
        bit_depth=bit_depth,
        scaling="shared",
        image_shape=image.image_shape,
        energy_min=image.energy_min,
        energy_max=image.energy_max,
        output_path=final_path,
    )


def write_slice_export(
    input_xsf: Path,
    *,
    output_path: Path | None,
    axis: str,
    index: int | None,
    indices: list[int] | None,
    count: int | None,
    invert: bool,
    geometry: str,
    pixels_per_angstrom: float | None,
    background: str,
    bit_depth: int,
    scaling: str,
    force: bool,
) -> tuple[SliceExportResult, Path]:
    text = input_xsf.read_text(encoding="utf-8")
    output_bytes, export = export_xsf_slices_to_bytes(
        text,
        source_name=str(input_xsf),
        filename_stem=input_xsf.stem,
        axis=axis,
        index=index,
        indices=indices,
        count=count,
        invert=invert,
        geometry=geometry,
        pixels_per_angstrom=pixels_per_angstrom,
        background=background,
        bit_depth=bit_depth,
        scaling=scaling,
    )
    if output_path is None:
        if len(export.indices) == 1:
            final_path = default_output_path(
                input_xsf, axis, export.indices[0], geometry
            )
        else:
            final_path = default_archive_path(input_xsf, axis, geometry)
    else:
        final_path = output_path
    if final_path.exists() and not force:
        raise ValueError(f"{final_path} already exists; use --force to overwrite it")
    final_path.write_bytes(output_bytes)
    return export, final_path


def main() -> int:
    args = build_parser().parse_args()
    try:
        exact_indices = parse_slice_indices(args.indices) if args.indices is not None else None
        export, output_path = write_slice_export(
            args.input_xsf,
            output_path=args.output,
            axis=args.axis,
            index=args.index,
            indices=exact_indices,
            count=args.count,
            invert=args.invert,
            geometry=args.geometry,
            pixels_per_angstrom=args.pixels_per_angstrom,
            background=args.background,
            bit_depth=args.bit_depth,
            scaling=args.scaling,
            force=args.force,
        )
        shapes = set(export.image_shapes)
        image_description = (
            f"{export.image_shapes[0][0]} x {export.image_shapes[0][1]} pixels"
            if len(shapes) == 1
            else "varied image dimensions"
        )
        print(f"Axis:       {export.axis}")
        print(f"Slices:     {len(export.indices)}")
        print(f"Indices:    {', '.join(str(value) for value in export.indices)}")
        print(f"Geometry:   {export.geometry}")
        print(f"Bit depth:  {export.bit_depth}-bit")
        print(f"Scaling:    {export.scaling}")
        print(f"Image:      {image_description}")
        print(f"Energy:     {export.energy_min:.7f} to {export.energy_max:.7f} eV")
        print(f"Written:    {output_path}")
        return 0
    except (OSError, ValueError) as error:
        print_options()
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
