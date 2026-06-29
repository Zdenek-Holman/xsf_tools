# XSF Tools

Streamlit app and command-line helpers for simple XSF 3-D data-grid workflows:

- cut one XSF grid to a Cartesian or fractional coordinate region
- subtract values from two uploaded XSF maps, with optional minima alignment

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy On Streamlit Community Cloud

Create a new app from this GitHub repository and use:

- branch: `main`
- main file: `streamlit_app.py`

The app processes uploaded files in memory and returns downloadable `.xsf`
outputs. Large generated calculation files are not tracked in Git.
