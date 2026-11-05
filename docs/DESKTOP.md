# COVERAGEDIAGRAMS Desktop — Windows + macOS

The desktop application uses the **same** Streamlit UI and radar calculation code as
the web app. It runs a local Streamlit process listening only on 127.0.0.1 and
presents it in a native window with Windows WebView2 or macOS WebKit.

It **does not require an installed Python interpreter** on the target device
once the portable application has been built.

## Get a prebuilt app from GitHub Actions

1. Open [Build Windows and macOS Desktop](https://github.com/matykropac/COVERAGEDIAGRAMS/actions/workflows/desktop-build.yml).
2. Open a successful run or click **Run workflow** on the main branch.
3. Download the artifact for **Windows x64**, **macOS Apple Silicon**, or
   **macOS Intel**. The downloaded artifact contains a ZIP file; unzip it.
4. Windows: copy the entire `COVERAGEDIAGRAMS` directory and launch
   `COVERAGEDIAGRAMS.exe`. Microsoft Edge **WebView2 Runtime** may be needed
   (usually already installed on Windows 11).
5. macOS: unzip preserving the application bundle, move
   `COVERAGEDIAGRAMS.app` to Applications, and launch it. These builds are
   **not notarized**; Gatekeeper may block the first opening. Prefer a locally
   built version or a signed release if required by your organization's policy.

## Build from source

Requires Python **3.12**.

Windows: run `build_windows.bat` from the repository root.

macOS:
```bash
bash build_mac.sh
```

Or manually:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-desktop.txt
pyinstaller --clean --noconfirm desktop.spec
```

The PyInstaller configuration is at **repository root** (`desktop.spec`);
do not use legacy paths involving `desktop/`.

## Actual offline behavior

**Local**: application UI, calculation code, imported DEM/GeoTIFF/GeoJSON/CSV,
project save/load, locally cached raster tiles, analytical exports.

**Internet-dependent**: loading new OpenStreetMap/Esri basemap tiles,
OpenTopography DEM API, public OSM/Microsoft buildings, airports, ADS-B traffic,
and external data providers. These will not become offline merely by packaging
the user interface. Use local terrain datasets / saved projects when disconnected.

## Privacy and diagnostics

- Listens on `127.0.0.1` and chooses an unused local port; it is not exposed
  on the LAN.
- The desktop window is a web view, not an external browser tab.
- No remote upload is required for calculations using locally imported datasets.
- Logs:
  - Windows: `%LOCALAPPDATA%\COVERAGEDIAGRAMS\desktop-startup.log`
  - macOS: `~/Library/Application Support/COVERAGEDIAGRAMS/desktop-startup.log`
- Closing the desktop window terminates the corresponding local Streamlit server.

## Limitations

- GitHub Actions smoke test validates that the **packaged local server starts**;
  it does not perform automated interaction with the native GUI.
- Applications are unsigned/not notarized; no MSIX/DMG installation experience
  is provided yet. Windows is supplied as a portable ZIP, macOS as a zipped
  .app.
- GitHub Actions artifacts are stored for 30 days; build times depend on runner
  availability and package size.
