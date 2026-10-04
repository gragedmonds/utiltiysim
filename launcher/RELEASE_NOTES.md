Download **UtilityStudio** for your computer: Windows opens the `.exe`; macOS and Linux unzip the launcher first.
The `runtime-*` files are downloaded automatically by the launcher; you do not need to choose one yourself.

Open it (on Windows there is no console window: the page in your browser is the app, with **Quit Utility Studio** at
the bottom, and opening the executable again brings that page back). Keep or change the storage folder, and click
**Open Utility Studio**. The first start downloads and verifies
the engine into that folder; later starts reuse it. Utility Studio then opens in your browser: set up a simulation,
tweak any setting, run the year and read the results, all on this computer. Nothing is uploaded.

**Simulation files.** Export a simulation in Studio and import the file in Utility Studio on another computer: the same
town, homes, seed, settings, dates and every scenario on the year come across. Each file is named by three words,
such as `brave-otter-harbour.utilitysim.json`.

**Talk it through** with Claude is optional and needs an internet connection and an Anthropic API key, which you
paste into the guide's panel; it is kept in your computer's secure storage.

The engine has a pinned SHA-256 digest and Ed25519 signature verified by the launcher. These builds have no Apple
notarization or Windows publisher certificate, so the operating system may show an unidentified-publisher prompt.
Linux needs a desktop browser and glibc 2.35 or newer. Measured sizes are in each platform's manifest JSON.
