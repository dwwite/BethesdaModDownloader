# Dwwite Downloader

This is a small tool for pulling public mods from Bethesda.net and Creations links. If you're a GOG user or a 🏴‍☠️ (i hope you arent) this mod is for you.

## What it does

The downloader can take:

- older `bethesda.net` mod links
- newer `creations.bethesda.net` links
- numeric mod IDs
- plain text searches

Once it finds the mod, it grabs the latest public file for the platform you selected. If Bethesda serves that download as a `.ckm` container, the tool automatically unpacks it into the real mod files like `.esp`, `.ba2`, and `.ini`, then writes a `manifest.json` so you can see exactly what was pulled.

## Running it

If you want the packaged app, build it and run the `.exe`:

```powershell
.\dist\BethesdaModDownloader.exe
```

That single `.exe` already includes the Python script and the GUI.

If you want to run it from source instead:

```powershell
python .\bethesda_mod_downloader.py --gui
```

You can also use it from the command line.

List a mod without downloading:

```powershell
python .\bethesda_mod_downloader.py 4225788 --product fallout4 --platform WINDOWS --list-only
```

Download a mod:

```powershell
python .\bethesda_mod_downloader.py "https://bethesda.net/en/mods/fallout4/mod-detail/4225788" --product fallout4 --platform WINDOWS
```

## Project files

- `bethesda_mod_downloader.py` is the main script and contains the GUI.
- `launch_bethesda_downloader.bat` starts the source version with Python.
- `build_bethesda_downloader_exe.bat` builds the single-file Windows `.exe`.

## Limits

This only works with file URLs Bethesda exposes publicly. Some creations, especially Verified Creator or library-gated ones, still have to be installed from the in-game Creations menu because Bethesda does not hand out a public download URL for them. And I am not gonna reverse engineer or get Bethesda's lawyers up my ass for giving people free access to paid mods

Windows Defender may also flag unsigned packaged builds. If that happens, and you do not trust the packaged app, use the Python source version instead.
