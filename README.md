# XSF Tools

Streamlit app and command-line helpers for simple XSF 3-D data-grid workflows.

The Streamlit app includes TIFF slice export from XSF energy maps:

- export one exact slice or multiple exact/equidistant slices
- render in raw grid space or real-space lattice geometry
- choose normalized 32-bit float TIFF (default) or 16-bit integer TIFF
- use shared brightness scaling for comparison or scale every slice separately
- download multiple slices together as a ZIP
- optionally invert brightness
- optionally add raw-valued atom-position TIFFs using periodic 3-D sphere cuts
- set a separate sphere radius in Å for every detected element

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
