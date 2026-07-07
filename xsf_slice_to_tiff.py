#!/usr/bin/env python3
"""Convert one 2-D slice of an XSF energy grid to a 16-bit TIFF image."""

from __future__ import annotations

import argparse
import sys
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from xsf_tools import parse_cut_grid_text


AXIS_TO_NUMBER = {"x": 0, "y": 1, "z": 2}
PLANE_AXES = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}


@dataclass(frozen=True)
class SliceResult:
    axis: str
    index: int
    geometry: str
    image_shape: tuple[int, int]
    energy_min: float
    energy_max: float
    output_path: Path


@dataclass(frozen=True)
class SliceImageResult:
    axis: str
    index: int
    geometry: str
    image_shape: tuple[int, int]
    energy_min: float
    energy_max: float
    image_data: np.ndarray


def print_options(file=sys.stderr) -> None:
    print(
        "Create a 16-bit grayscale TIFF from one 2-D slice of an XSF energy map.\n"
        "\n"
        "Examples:\n"
        "python3 xsf_slice_to_tiff.py diff/energy_grid_Y.xsf\n"
        "python3 xsf_slice_to_tiff.py diff/energy_grid_Y.xsf --axis z --index 20 -o cut_z20.tiff\n"
        "python3 xsf_slice_to_tiff.py diff/energy_grid_Y.xsf --axis z --geometry real\n"
        "python3 xsf_slice_to_tiff.py diff/energy_grid_Y_minus_energy_grid_Nd.xsf --axis y --index 35 --invert\n",
        file=file,
    )


class SliceArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print_options()
        self.exit(2, f"Error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = SliceArgumentParser(
        description="Write one 2-D cut through an XSF 3-D energy grid as a 16-bit TIFF."
    )
    parser.add_argument("input_xsf", type=Path, help="input XSF energy map")
    parser.add_argument("-o", "--output", type=Path, help="output TIFF path")
    parser.add_argument(
        "--axis",
        choices=("x", "y", "z"),
        default="z",
        help="axis perpendicular to the cut plane (default: z)",
    )
    parser.add_argument(
        "--index",
        type=int,
        help="slice index along the selected axis (default: middle slice)",
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
        help="render in square grid-index space or projected real space (default: grid)",
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


def default_output_path(input_xsf: Path, axis: str, index: int, geometry: str) -> Path:
    suffix = f"{axis}{index:03d}"
    if geometry == "real":
        suffix += "_real"
    return input_xsf.with_name(f"{input_xsf.stem}_{suffix}.tiff")


def extract_slice(data: np.ndarray, axis: str, index: int) -> np.ndarray:
    axis_number = AXIS_TO_NUMBER[axis]
    if axis_number == 0:
        slice_2d = data[index, :, :]
    elif axis_number == 1:
        slice_2d = data[:, index, :]
    else:
        slice_2d = data[:, :, index]

    # Numpy arrays use row, column for images. Transpose so the first remaining
    # grid axis goes left-to-right and the second remaining axis goes top-to-bottom.
    return np.asarray(slice_2d, dtype=float).T


def extract_slice_plane(data: np.ndarray, axis: str, index: int) -> np.ndarray:
    """Return a 2-D slice with dimensions matching the two in-plane grid axes."""
    axis_number = AXIS_TO_NUMBER[axis]
    if axis_number == 0:
        return np.asarray(data[index, :, :], dtype=float)
    if axis_number == 1:
        return np.asarray(data[:, index, :], dtype=float)
    return np.asarray(data[:, :, index], dtype=float)


def scale_to_uint16(slice_2d: np.ndarray, invert: bool) -> tuple[np.ndarray, float, float]:
    energy_min = float(np.nanmin(slice_2d))
    energy_max = float(np.nanmax(slice_2d))
    if not np.isfinite(energy_min) or not np.isfinite(energy_max):
        raise ValueError("slice contains no finite energy values")

    if energy_max > energy_min:
        scaled = (slice_2d - energy_min) * (65535.0 / (energy_max - energy_min))
    else:
        scaled = np.zeros_like(slice_2d, dtype=float)

    if invert:
        scaled = 65535.0 - scaled

    image_data = np.rint(np.clip(scaled, 0.0, 65535.0)).astype(np.uint16)
    return image_data, energy_min, energy_max


def scale_with_limits(
    values: np.ndarray,
    energy_min: float,
    energy_max: float,
    invert: bool,
) -> np.ndarray:
    if energy_max > energy_min:
        scaled = (values - energy_min) * (65535.0 / (energy_max - energy_min))
    else:
        scaled = np.zeros_like(values, dtype=float)

    if invert:
        scaled = 65535.0 - scaled

    return np.rint(np.clip(scaled, 0.0, 65535.0)).astype(np.uint16)


def project_plane_vectors(vector_u: np.ndarray, vector_v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
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


def bilinear_sample(plane: np.ndarray, u_fraction: np.ndarray, v_fraction: np.ndarray) -> np.ndarray:
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


def render_real_space_slice(
    plane: np.ndarray,
    vector_u: np.ndarray,
    vector_v: np.ndarray,
    pixels_per_angstrom: float | None,
    invert: bool,
    background: str,
) -> tuple[np.ndarray, float, float, float]:
    vector_u_2d, vector_v_2d = project_plane_vectors(vector_u, vector_v)

    if pixels_per_angstrom is None:
        pixels_per_angstrom = default_pixels_per_angstrom(
            plane.shape,
            vector_u_2d,
            vector_v_2d,
        )
    if pixels_per_angstrom <= 0.0:
        raise ValueError("--pixels-per-angstrom must be greater than zero")

    corners = np.array(
        [
            [0.0, 0.0],
            vector_u_2d,
            vector_v_2d,
            vector_u_2d + vector_v_2d,
        ],
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
    inverse_basis = np.linalg.inv(basis)
    coordinates = np.stack([x.ravel(), y.ravel()], axis=0)
    fractions = inverse_basis @ coordinates
    u_fraction = fractions[0].reshape((height, width))
    v_fraction = fractions[1].reshape((height, width))

    tolerance = 1e-9
    inside = (
        (u_fraction >= -tolerance)
        & (u_fraction <= 1.0 + tolerance)
        & (v_fraction >= -tolerance)
        & (v_fraction <= 1.0 + tolerance)
    )

    energy_min = float(np.nanmin(plane))
    energy_max = float(np.nanmax(plane))
    if not np.isfinite(energy_min) or not np.isfinite(energy_max):
        raise ValueError("slice contains no finite energy values")

    sampled = bilinear_sample(plane, u_fraction, v_fraction)
    scaled = scale_with_limits(sampled, energy_min, energy_max, invert=invert)
    background_value = np.uint16(0 if background == "black" else 65535)
    image_data = np.full((height, width), background_value, dtype=np.uint16)
    image_data[inside] = scaled[inside]

    return image_data, energy_min, energy_max, pixels_per_angstrom


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
) -> SliceResult:
    text = input_xsf.read_text(encoding="utf-8")
    image_result = render_slice_image(
        text,
        source_name=str(input_xsf),
        axis=axis,
        index=index,
        invert=invert,
        geometry=geometry,
        pixels_per_angstrom=pixels_per_angstrom,
        background=background,
    )
    final_output_path = output_path or default_output_path(
        input_xsf,
        image_result.axis,
        image_result.index,
        image_result.geometry,
    )
    if final_output_path.exists() and not force:
        raise ValueError(f"{final_output_path} already exists; use --force to overwrite it")

    image = Image.fromarray(image_result.image_data, mode="I;16")
    image.save(final_output_path)

    return SliceResult(
        axis=image_result.axis,
        index=image_result.index,
        geometry=image_result.geometry,
        image_shape=image_result.image_shape,
        energy_min=image_result.energy_min,
        energy_max=image_result.energy_max,
        output_path=final_output_path,
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
) -> SliceImageResult:
    if axis not in AXIS_TO_NUMBER:
        raise ValueError(f"unknown axis {axis!r}; use 'x', 'y', or 'z'")
    if geometry not in {"grid", "real"}:
        raise ValueError(f"unknown geometry {geometry!r}; use 'grid' or 'real'")
    if background not in {"black", "white"}:
        raise ValueError(f"unknown background {background!r}; use 'black' or 'white'")

    grid = parse_cut_grid_text(input_text, source_name=source_name)

    axis_number = AXIS_TO_NUMBER[axis]
    axis_size = grid.shape[axis_number]
    if index is None:
        index = axis_size // 2
    if index < 0 or index >= axis_size:
        raise ValueError(
            f"index {index} is outside axis {axis!r}; valid range is 0..{axis_size - 1}"
        )

    if geometry == "grid":
        slice_2d = extract_slice(grid.data, axis, index)
        image_data, energy_min, energy_max = scale_to_uint16(slice_2d, invert=invert)
    else:
        plane = extract_slice_plane(grid.data, axis, index)
        plane_axis_u, plane_axis_v = PLANE_AXES[axis]
        image_data, energy_min, energy_max, pixels_per_angstrom = render_real_space_slice(
            plane,
            grid.vectors[plane_axis_u],
            grid.vectors[plane_axis_v],
            pixels_per_angstrom=pixels_per_angstrom,
            invert=invert,
            background=background,
        )

    return SliceImageResult(
        axis=axis,
        index=index,
        geometry=geometry,
        image_shape=(int(image_data.shape[1]), int(image_data.shape[0])),
        energy_min=energy_min,
        energy_max=energy_max,
        image_data=image_data,
    )


def slice_xsf_text_to_tiff_bytes(
    input_text: str,
    source_name: str = "uploaded.xsf",
    axis: str = "z",
    index: int | None = None,
    invert: bool = False,
    geometry: str = "grid",
    pixels_per_angstrom: float | None = None,
    background: str = "black",
) -> tuple[bytes, SliceImageResult]:
    result = render_slice_image(
        input_text,
        source_name=source_name,
        axis=axis,
        index=index,
        invert=invert,
        geometry=geometry,
        pixels_per_angstrom=pixels_per_angstrom,
        background=background,
    )
    buffer = BytesIO()
    Image.fromarray(result.image_data, mode="I;16").save(buffer, format="TIFF")
    return buffer.getvalue(), result


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = write_slice_tiff(
            args.input_xsf,
            output_path=args.output,
            axis=args.axis,
            index=args.index,
            invert=args.invert,
            geometry=args.geometry,
            pixels_per_angstrom=args.pixels_per_angstrom,
            background=args.background,
            force=args.force,
        )
        print(f"Axis:       {result.axis}")
        print(f"Index:      {result.index}")
        print(f"Geometry:   {result.geometry}")
        print(f"Image:      {result.image_shape[0]} x {result.image_shape[1]} pixels")
        print(f"Energy:     {result.energy_min:.7f} to {result.energy_max:.7f} eV")
        print(f"Written:    {result.output_path}")
        return 0
    except (OSError, ValueError) as error:
        print_options()
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
