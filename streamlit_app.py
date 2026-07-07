from __future__ import annotations

from pathlib import Path

import streamlit as st

from xsf_slice_to_tiff import slice_xsf_text_to_tiff_bytes


def _decode_upload(uploaded_file) -> str:
    try:
        return uploaded_file.getvalue().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("uploaded file is not valid UTF-8 text") from error


def _stem(filename: str, fallback: str) -> str:
    stem = Path(filename).stem
    return stem or fallback


st.set_page_config(page_title="XSF Slice TIFF", layout="centered")
st.title("XSF Slice TIFF")

st.write(
    "Upload an XSF energy map, choose one slice, and export it as a 16-bit "
    "grayscale TIFF."
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
        """
    )

xsf_file = st.file_uploader("XSF file", type=["xsf"])

columns = st.columns(3)
with columns[0]:
    axis = st.selectbox("Slice axis", ["x", "y", "z"], index=2)
with columns[1]:
    index = st.number_input("Slice index", min_value=0, value=0, step=1)
with columns[2]:
    geometry = st.selectbox("Geometry", ["grid", "real"])

invert = st.checkbox("Invert brightness")

if st.button("Generate TIFF", type="primary"):
    if xsf_file is None:
        st.warning("Upload an XSF file first.")
    else:
        try:
            tiff_bytes, stats = slice_xsf_text_to_tiff_bytes(
                _decode_upload(xsf_file),
                source_name=xsf_file.name,
                axis=axis,
                index=int(index),
                invert=invert,
                geometry=geometry,
                pixels_per_angstrom=None,
                background="black",
            )
        except ValueError as error:
            st.error(str(error))
        else:
            suffix = f"{stats.axis}{stats.index:03d}"
            if stats.geometry == "real":
                suffix += "_real"
            filename = f"{_stem(xsf_file.name, 'energy_grid')}_{suffix}.tiff"

            metric_columns = st.columns(4)
            metric_columns[0].metric("Axis", stats.axis)
            metric_columns[1].metric("Index", stats.index)
            metric_columns[2].metric("Geometry", stats.geometry)
            metric_columns[3].metric(
                "Image",
                f"{stats.image_shape[0]} × {stats.image_shape[1]}",
            )
            st.metric(
                "Energy range",
                f"{stats.energy_min:.7f} to {stats.energy_max:.7f} eV",
            )

            st.download_button(
                "Download TIFF",
                data=tiff_bytes,
                file_name=filename,
                mime="image/tiff",
            )
