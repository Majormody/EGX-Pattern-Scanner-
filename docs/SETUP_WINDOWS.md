# Windows quick setup

1. Install Python 3.11 or 3.12.
2. Open PowerShell in this project directory.
3. Run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If activation is blocked in this PowerShell session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Initial setup and first scan:

```powershell
python -m egx_scanner.cli universe
python -m egx_scanner.cli prices --period 2y
python -m egx_scanner.cli coverage
python -m egx_scanner.cli scan --no-refresh
```

Dashboard:

```powershell
streamlit run app.py
```

Tests (no network needed):

```powershell
python -m unittest discover -s tests -v
```
