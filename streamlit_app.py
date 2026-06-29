from __future__ import annotations

from pathlib import Path

import streamlit as st

from xsf_tools import cut_xsf_text, subtract_xsf_text


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

cut_tab, subtract_tab = st.tabs(["Cut XSF", "Subtract XSF"])

with cut_tab:
    cut_file = st.file_uploader("XSF file", type=["xsf"], key="cut_file")

    mode = st.radio(
        "Coordinates",
        ["cartesian", "fractional"],
        horizontal=True,
        key="cut_coordinate_mode",
    )

    if mode == "fractional":
        default_bounds = ((0.0, 1.0), (0.0, 1.0), (0.0, 1.0))
    else:
        default_bounds = ((-100.0, 100.0), (-100.0, 100.0), (5.0, 6.0))

    bound_columns = st.columns(3)
    axes = ("x", "y", "z")
    bounds = []
    for column, axis, default in zip(bound_columns, axes, default_bounds):
        with column:
            lower = st.number_input(
                f"{axis} min",
                value=default[0],
                format="%.7f",
                key=f"cut_{mode}_{axis}_min",
            )
            upper = st.number_input(
                f"{axis} max",
                value=default[1],
                format="%.7f",
                key=f"cut_{mode}_{axis}_max",
            )
            bounds.append((lower, upper))

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
                result_text, stats = cut_xsf_text(
                    _decode_upload(cut_file),
                    bounds,
                    coordinate_mode=mode,
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

with subtract_tab:
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
