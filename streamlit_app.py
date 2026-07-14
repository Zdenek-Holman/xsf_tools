from __future__ import annotations

from pathlib import Path

import streamlit as st

from xsf_slice_to_tiff import (
    export_xsf_slices_to_bytes,
    parse_slice_indices,
    select_slice_indices,
)
from xsf_tools import (
    cut_xsf_box_text,
    cut_xsf_text,
    parse_cut_grid_text,
    subtract_xsf_text,
)


def _decode_upload(uploaded_file) -> str:
    try:
        return uploaded_file.getvalue().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("uploaded file is not valid UTF-8 text") from error


def _stem(filename: str, fallback: str) -> str:
    stem = Path(filename).stem
    return stem or fallback


def _format_grid(shape: tuple[int, int, int]) -> str:
    return " x ".join(str(value) for value in shape)


st.set_page_config(page_title="XSF Tools", layout="wide")
st.title("XSF Tools")

tool = st.radio(
    "Tool",
    ["Cut XSF", "Subtract XSF", "Slice TIFF"],
    horizontal=True,
)

if tool == "Cut XSF":
    cut_file = st.file_uploader("XSF file", type=["xsf"], key="cut_file")

    cut_shape = st.radio(
        "Cut shape",
        ["bounds", "box"],
        horizontal=True,
        key="cut_shape",
    )
    mode = st.radio(
        "Coordinates / point units",
        ["cartesian", "fractional"],
        horizontal=True,
        key="cut_coordinate_mode",
    )

    bounds = None
    points = None
    if cut_shape == "bounds":
        if mode == "fractional":
            default_bounds = ((0.0, 1.0), (0.0, 1.0), (0.0, 1.0))
        else:
            default_bounds = ((-100.0, 100.0), (-100.0, 100.0), (5.0, 6.0))

        bound_columns = st.columns(3)
        bounds = []
        for column, axis, default in zip(bound_columns, ("x", "y", "z"), default_bounds):
            with column:
                lower = st.number_input(
                    f"{axis} min",
                    value=default[0],
                    format="%.7f",
                    key=f"cut_bounds_{mode}_{axis}_min",
                )
                upper = st.number_input(
                    f"{axis} max",
                    value=default[1],
                    format="%.7f",
                    key=f"cut_bounds_{mode}_{axis}_max",
                )
                bounds.append((lower, upper))
    else:
        st.caption(
            "Box definition: u = B − A, v = C − B, w = D − A. "
            "Points inside A + s*u + t*v + r*w with 0 ≤ s,t,r ≤ 1 are kept."
        )
        default_points = {
            "A": (0.0, 0.0, 0.0),
            "B": (1.0, 0.0, 0.0),
            "C": (1.0, 1.0, 0.0),
            "D": (0.0, 0.0, 1.0),
        }
        points = {}
        for point_name, defaults in default_points.items():
            columns = st.columns(3)
            point_values = []
            for column, axis, default in zip(columns, ("x", "y", "z"), defaults):
                with column:
                    point_values.append(
                        st.number_input(
                            f"{point_name}{axis}",
                            value=default,
                            format="%.7f",
                            key=f"cut_box_{mode}_{point_name}_{axis}",
                        )
                    )
            points[point_name] = tuple(point_values)

    value_columns = st.columns(2)
    with value_columns[0]:
        outside_value = st.number_input(
            "Outside value",
            value=0.0,
            format="%.7f",
            key="cut_outside_value",
        )
    with value_columns[1]:
        use_fill_value = st.checkbox("Fill selected region", key="cut_use_fill")
        fill_value = st.number_input(
            "Selected value",
            value=0.0,
            format="%.7f",
            key="cut_fill_value",
            disabled=not use_fill_value,
        )

    if st.button("Generate cut XSF", type="primary", key="generate_cut"):
        if cut_file is None:
            st.warning("Upload an XSF file first.")
        else:
            try:
                if cut_shape == "bounds":
                    result_text, stats = cut_xsf_text(
                        _decode_upload(cut_file),
                        bounds,
                        coordinate_mode=mode,
                        outside_value=outside_value,
                        test_value=fill_value if use_fill_value else None,
                        source_name=cut_file.name,
                    )
                else:
                    result_text, stats = cut_xsf_box_text(
                        _decode_upload(cut_file),
                        points["A"],
                        points["B"],
                        points["C"],
                        points["D"],
                        point_mode=mode,
                        outside_value=outside_value,
                        test_value=fill_value if use_fill_value else None,
                        source_name=cut_file.name,
                    )
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state.cut_result_text = result_text
                st.session_state.cut_result_filename = f"{_stem(cut_file.name, 'energy_grid')}_region.xsf"
                st.session_state.cut_stats = stats

    if "cut_result_text" in st.session_state:
        stats = st.session_state.cut_stats
        metric_columns = st.columns(4)
        metric_columns[0].metric("Grid", _format_grid(stats.shape))
        metric_columns[1].metric("Selected points", f"{stats.selected_points:,}")
        metric_columns[2].metric("Total points", f"{stats.total_points:,}")
        metric_columns[3].metric(
            "Output range",
            f"{stats.output_min:.7f} to {stats.output_max:.7f}",
        )
        st.download_button(
            "Download cut XSF",
            data=st.session_state.cut_result_text,
            file_name=st.session_state.cut_result_filename,
            mime="text/plain",
            key="download_cut",
        )

elif tool == "Subtract XSF":
    upload_columns = st.columns(2)
    with upload_columns[0]:
        map_a = st.file_uploader("Map A", type=["xsf"], key="subtract_map_a")
    with upload_columns[1]:
        map_b = st.file_uploader("Map B", type=["xsf"], key="subtract_map_b")

    align_minima = st.checkbox("Align minima", key="subtract_align_minima")
    offset_columns = st.columns(2)
    with offset_columns[0]:
        offset_a_input = st.number_input(
            "Offset A (eV)",
            value=0.0,
            format="%.7f",
            disabled=align_minima,
            key="subtract_offset_a",
        )
    with offset_columns[1]:
        offset_b_input = st.number_input(
            "Offset B (eV)",
            value=0.0,
            format="%.7f",
            disabled=align_minima,
            key="subtract_offset_b",
        )

    if st.button("Generate difference XSF", type="primary", key="generate_subtract"):
        if map_a is None or map_b is None:
            st.warning("Upload both XSF maps first.")
        else:
            try:
                offset_a = 0.0 if align_minima else offset_a_input
                offset_b = 0.0 if align_minima else offset_b_input
                result_text, stats = subtract_xsf_text(
                    _decode_upload(map_a),
                    _decode_upload(map_b),
                    offset_a=offset_a,
                    offset_b=offset_b,
                    align_minima=align_minima,
                    map_a_name=map_a.name,
                    map_b_name=map_b.name,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                stem_a = _stem(map_a.name, "map_a")
                stem_b = _stem(map_b.name, "map_b")
                st.session_state.subtract_result_text = result_text
                st.session_state.subtract_result_filename = f"{stem_a}_minus_{stem_b}_values.xsf"
                st.session_state.subtract_stats = stats

    if "subtract_result_text" in st.session_state:
        stats = st.session_state.subtract_stats
        metric_columns = st.columns(4)
        metric_columns[0].metric("Values", f"{stats.values:,}")
        metric_columns[1].metric("Map A min", f"{stats.map_a_min:.7f} eV")
        metric_columns[2].metric("Map B min", f"{stats.map_b_min:.7f} eV")
        metric_columns[3].metric(
            "Result range",
            f"{stats.result_min:.7f} to {stats.result_max:.7f} eV",
        )
        offset_columns = st.columns(2)
        offset_columns[0].metric("Applied offset A", f"{stats.offset_a:+.7f} eV")
        offset_columns[1].metric("Applied offset B", f"{stats.offset_b:+.7f} eV")
        st.download_button(
            "Download difference XSF",
            data=st.session_state.subtract_result_text,
            file_name=st.session_state.subtract_result_filename,
            mime="text/plain",
            key="download_subtract",
        )

elif tool == "Slice TIFF":
    st.write(
        "Upload an XSF energy map and export one or more slices as 16-bit integer "
        "or 32-bit float grayscale TIFF images."
    )

    with st.expander("What do grid and real mean?", expanded=False):
        st.markdown(
            """
            **Grid** draws the slice exactly as the XSF data array is stored.
            A `71 × 71` slice becomes a square `71 × 71` image.

            **Real** draws the same slice using the XSF lattice vectors. For an
            oblique or hexagonal cell, the energy map appears as a skewed
            parallelogram/rhombus inside the rectangular TIFF canvas.

            **Invert** flips the brightness scale. Without inversion, low energy is
            dark and high energy is bright. With inversion, low energy is bright.

            **32-bit** stores normalized floating-point brightness values from
            `0.0` to `1.0`. **16-bit** stores integer brightness values from `0`
            to `65535`. The TIFFs are visualizations; the displayed energy range
            remains available separately in eV.
            """
        )

    slice_file = st.file_uploader("XSF file", type=["xsf"], key="slice_file")

    slice_columns = st.columns(4)
    with slice_columns[0]:
        slice_axis = st.selectbox("Slice axis", ["x", "y", "z"], index=2, key="slice_axis")
    with slice_columns[1]:
        slice_geometry = st.selectbox(
            "Geometry",
            ["grid", "real"],
            key="slice_geometry",
        )
    with slice_columns[2]:
        slice_bit_depth = st.selectbox(
            "Bit depth",
            [32, 16],
            format_func=lambda value: f"{value}-bit",
            key="slice_bit_depth",
        )
    with slice_columns[3]:
        slice_scaling = st.selectbox(
            "Brightness scaling",
            ["shared", "per-slice"],
            format_func=lambda value: (
                "Shared across slices"
                if value == "shared"
                else "Each slice separately"
            ),
            key="slice_scaling",
        )

    selection_mode = st.radio(
        "Slice selection",
        ["Exact indices", "Equidistant"],
        horizontal=True,
        key="slice_selection_mode",
    )
    if selection_mode == "Exact indices":
        slice_indices_text = st.text_input(
            "Slice indices",
            value="0",
            help="Enter comma-separated grid indices, for example: 0, 12, 45",
            key="slice_indices_text",
        )
        slice_count = None
    else:
        slice_indices_text = None
        slice_count = st.number_input(
            "Number of slices",
            min_value=1,
            value=1,
            step=1,
            help="Slices include both ends of the selected axis. One slice uses the middle.",
            key="slice_count",
        )

    invert_slice = st.checkbox("Invert brightness", key="slice_invert")

    slice_text = None
    selected_preview = None
    upload_error = None
    if slice_file is not None:
        try:
            slice_text = _decode_upload(slice_file)
            uploaded_grid = parse_cut_grid_text(
                slice_text,
                source_name=slice_file.name,
            )
            axis_size = uploaded_grid.shape[{"x": 0, "y": 1, "z": 2}[slice_axis]]
            exact_indices = (
                parse_slice_indices(slice_indices_text)
                if selection_mode == "Exact indices"
                else None
            )
            selected_preview = select_slice_indices(
                axis_size,
                indices=exact_indices,
                count=int(slice_count) if selection_mode == "Equidistant" else None,
            )
        except ValueError as error:
            upload_error = str(error)

    if selected_preview is not None:
        st.caption(
            f"Selected {len(selected_preview)} slice(s) from axis positions "
            f"0–{axis_size - 1}: {', '.join(str(value) for value in selected_preview)}"
        )
    elif upload_error is not None:
        st.warning(upload_error)

    if st.button("Generate TIFF", type="primary", key="generate_slice"):
        if slice_file is None:
            st.warning("Upload an XSF file first.")
        elif upload_error is not None:
            st.error(upload_error)
        else:
            try:
                output_bytes, stats = export_xsf_slices_to_bytes(
                    slice_text,
                    source_name=slice_file.name,
                    filename_stem=_stem(slice_file.name, "energy_grid"),
                    axis=slice_axis,
                    indices=(
                        selected_preview
                        if selection_mode == "Exact indices"
                        else None
                    ),
                    count=(
                        int(slice_count)
                        if selection_mode == "Equidistant"
                        else None
                    ),
                    invert=invert_slice,
                    geometry=slice_geometry,
                    pixels_per_angstrom=None,
                    background="black",
                    bit_depth=int(slice_bit_depth),
                    scaling=slice_scaling,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state.slice_output_bytes = output_bytes
                st.session_state.slice_result_filename = stats.filename
                st.session_state.slice_result_mime = stats.mime_type
                st.session_state.slice_stats = stats

    if "slice_output_bytes" in st.session_state:
        stats = st.session_state.slice_stats
        metric_columns = st.columns(5)
        metric_columns[0].metric("Axis", stats.axis)
        metric_columns[1].metric("Slices", len(stats.indices))
        metric_columns[2].metric("Geometry", stats.geometry)
        metric_columns[3].metric("Bit depth", f"{stats.bit_depth}-bit")
        metric_columns[4].metric("Scaling", stats.scaling)
        shapes = set(stats.image_shapes)
        if len(shapes) == 1:
            image_shape = stats.image_shapes[0]
            st.metric("Image size", f"{image_shape[0]} × {image_shape[1]}")
        else:
            st.metric("Image size", "Varies")
        st.caption(f"Generated indices: {', '.join(str(value) for value in stats.indices)}")
        st.metric("Energy range", f"{stats.energy_min:.7f} to {stats.energy_max:.7f} eV")
        st.download_button(
            "Download TIFF" if len(stats.indices) == 1 else "Download TIFF ZIP",
            data=st.session_state.slice_output_bytes,
            file_name=st.session_state.slice_result_filename,
            mime=st.session_state.slice_result_mime,
            key="download_slice",
        )
