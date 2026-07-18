# Bethesda Mod Downloader

This program allows you to download Bethesda mods directly from Bethesda.net. This is useful for those like myself who have the GOG version. (for the less legitmate owners of bethesda games this should work for you too)

# How does it work?
The program first requires you to input the link of the mod you want. Then on the right hand side you will choose between all platforms. The reason for this is that a mod you may want may not be on PC so instead you will download the mod from xbox or playstation instead. 

Then, click "Download latest" and the program will scan Bethesda's public API for any file it can download. if successful, it should output a .ckm file. You do not have to worry about attempting to decode it the program does that itself. Now it should be in the Downloads folder.

# Notes
1. This only works with non verified free mods. Any mod that is paid, made by a verified user or a free mod that says it only needs 0 credits will not work. This is because (i think) these mods are hosted on Bethesda's backend. I am not gonna attempt accessing it because i dont want Bethesda's foot up my ass.
2. Always check whether the mods work or not. .ckm files are kind of hard to work with so make sure to look out for any errors. 
3. You might get a warning from Windows Defender. This is just a false positive. Defender tends to flag Python packages that are unsigned for whatever reasom.
