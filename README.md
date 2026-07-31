# CSV Cleaner

CSV Cleaner is a local desktop application for analyzing, cleaning, and standardizing CSV and XLSX files. Your data stays on your computer, and the source file is protected against accidental overwriting.

## Key features

* automatic CSV encoding and separator detection
* file selection through the system dialog or drag and drop
* sheet selection for XLSX workbooks
* preview of the first 100 records
* detection of empty rows and columns, duplicates, missing values, and unnecessary whitespace
* detection of potential date and email columns
* whitespace cleanup and column name standardization
* duplicate removal based on all columns or a selected subset
* missing value replacement with text, zero, mean, median, or mode
* date and letter case standardization
* preview of up to 500 example changes
* safe CSV or XLSX export through a temporary file
* TXT and JSON reports created with every export
* local error log stored in the user `.csv_cleaner` directory
* English and Polish interface with an instant EN and PL language switch

## Requirements

* Python 3.11 or newer
* Tkinter available in the Python installation

## Downloading the ready to use macOS application

1. Open the repository page on GitHub.
2. Go to the **Releases** section on the right.
3. Download the archive that matches your Mac:

| Mac processor | File |
|---|---|
| Apple Silicon, including M1, M2, M3, M4, and newer | `CSV-Cleaner-macOS-arm64.zip` |
| Intel | `CSV-Cleaner-macOS-x86_64.zip` |

4. Open the downloaded ZIP archive.
5. Move `CSV Cleaner.app` to the `Applications` folder.
6. On the first launch, right click the application and choose **Open**.

If macOS still blocks the application, open **System Settings**, go to **Privacy & Security**, and choose **Open Anyway**.

Packages published automatically by GitHub are not signed with an Apple Developer certificate. macOS may therefore display a warning on the first launch.

## Downloading the ready to use Windows application

1. Open the repository page on GitHub.
2. Go to the **Releases** section.
3. Download `CSV-Cleaner-Windows-x64.zip`.
4. Extract the archive to a folder of your choice.
5. Run `CSV Cleaner.exe`.

The Windows package is not signed with a commercial code signing certificate. Microsoft Defender SmartScreen may display a warning on the first launch. Choose **More info**, verify that the file came from this repository, and then choose **Run anyway**.

The published Windows package targets 64 bit versions of Windows 10 and Windows 11.

## Installing and running from source

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Running the application

```bash
python run.py
```

Choose a CSV or XLSX file with the button or drag it into the marked area. Review the data, start the analysis, select cleaning operations, inspect the planned changes, and save a new copy.

Use the EN and PL controls in the top right corner to switch the entire interface between English and Polish. The current data, selected cleaning options, and active step remain unchanged.

A sample file for a quick check is available at `sample_data/dirty_sample.csv`.

## Building the macOS application after downloading the source

The build requires macOS, Python 3.11 or newer, and Tk 8.6.13 or newer. The script automatically selects the newest compatible environment found on the computer. Download the source with **Code**, choose **Download ZIP**, extract it, open Terminal in the project directory, and run:

```bash
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

The script creates an isolated build environment, installs dependencies, builds the application, and prepares two files:

```text
dist/CSV Cleaner.app
dist/CSV-Cleaner-macOS-arm64.zip
```

The archive name depends on the computer processor and may also end with `x86_64.zip`.

## Building the Windows application after downloading the source

The build requires 64 bit Windows, Python 3.11 or newer, and Tkinter. Download and extract the source, open PowerShell in the project directory, and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The script creates an isolated build environment, runs all tests, builds a standalone executable, and prepares these files:

```text
dist/CSV Cleaner.exe
dist/CSV-Cleaner-Windows-x64.zip
```

The executable contains Python and all required libraries. Users do not need to install Python to run it.

## Tests

```bash
python -m pytest
```

The tests use the standard `unittest` library as well, so the basic verification can run without Pytest:

```bash
python -m unittest discover -v
```

On macOS, run the automated interface test to verify both languages, all five steps, buttons, scrolling, preview, export, and dynamic CSV and Excel options:

```bash
python scripts/test_ui_macos.py
```

## Automatic GitHub releases

The `.github/workflows/build.yml` workflow follows the same release approach as Photo Tools. Every version tag beginning with `v` runs the tests and builds three packages:

* macOS for Apple Silicon
* macOS for Intel
* Windows for 64 bit Intel and AMD processors

After all builds complete, GitHub creates a release and attaches all three archives.

Example release:

```bash
git tag v1.2.0
git push origin v1.2.0
```

The workflow can also be started manually from the **Actions** tab. A manual run stores the packages as workflow artifacts without publishing a new release.

## Manual PyInstaller build

After installing the dependencies on macOS, run:

```bash
pyinstaller csv_cleaner_macos.spec
```

The completed `CSV Cleaner.app` package will be available in the `dist` directory.

On Windows, run:

```powershell
python -m PyInstaller --clean --noconfirm csv_cleaner_windows.spec
```

The completed `CSV Cleaner.exe` file will be available in the `dist` directory.

## Data safety

The application performs all operations on an in memory copy of the data frame. Export first creates a temporary file and replaces the target only after a successful write. Overwriting an existing file requires confirmation in the interface.

## Project structure

File loading, analysis, cleaning, validation, export, and reporting logic is located in `csv_cleaner/core`. The Tkinter interface is located in `csv_cleaner/ui`, while configuration and result models are stored in `csv_cleaner/models`.
