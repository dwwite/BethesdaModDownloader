# Dwwite Downloader

Small downloader for public Bethesda.net and Creations links.

## Files

- `bethesda_mod_downloader.py` is the main script.
- `launch_bethesda_downloader.bat` starts the GUI with Python.
- `build_bethesda_downloader_exe.bat` builds a single-file Windows `.exe`.

## What it does

- Resolves old Bethesda mod links, newer Creations links, numeric IDs, and text searches.
- Downloads public files for the selected platform.
- Unpacks Bethesda `BTAR` `.ckm` containers into real mod files like `.esp`, `.ba2`, and `.ini`.
- Writes a `manifest.json` for each downloaded mod.

## Quick Start

Run the GUI:

```powershell
python .\bethesda_mod_downloader.py --gui
```

List a mod without downloading:

```powershell
python .\bethesda_mod_downloader.py 4225788 --product fallout4 --platform WINDOWS --list-only
```

Download a mod:

```powershell
python .\bethesda_mod_downloader.py "https://bethesda.net/en/mods/fallout4/mod-detail/4225788" --product fallout4 --platform WINDOWS
```

## Releases

- The repo keeps source only. Built app bundles should go in GitHub Releases, not in git.
- A GitHub Actions workflow at `.github/workflows/release.yml` builds a single-file Windows `.exe`.
- Run it manually from the Actions tab to get a downloadable artifact.
- Push a tag like `v1.0.0` to build the app and attach `BethesdaModDownloader.exe` to a GitHub release.

## Notes

- This downloader only works with public file URLs exposed by Bethesda.
- Some Verified Creator or library-gated Creations still have to be installed from the in-game Creations menu.
- Windows Defender may warn on unsigned packaged builds. If that happens, prefer reviewing or running the Python source directly.
- Build output and downloaded mods are ignored by git in this repo.
