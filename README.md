# XSF Tools

Streamlit app and command-line helpers for simple XSF 3-D data-grid workflows.

The online Streamlit app focuses on exporting 16-bit TIFF slices from XSF
energy maps:

- choose the slice axis and index
- render in raw grid space or real-space lattice geometry
- optionally invert brightness

- cut one XSF grid to Cartesian/fractional bounds or a 4-point oblique box
- subtract values from two uploaded XSF maps, with optional minima alignment
- use command-line helpers for cutting and subtracting XSF maps

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Use online on Streamlit Community Cloud

https://xsftools.streamlit.app/
