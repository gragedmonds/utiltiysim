Download the small **UtilityStudio** launcher for your computer. Windows users open the `.exe`; macOS/Linux users extract the launcher zip first. The `runtime-*` files are downloaded automatically; you do not need to choose one yourself.

Click **Choose folder** for the native folder selector, choose storage (for example `P:\UtilitySim`), let the launcher install its verified runtime, then enter the eight-character code from Studio. Reopening reconnects using the stored device link. The launcher and runtime must both remain running to receive jobs; cached jobs continue through internet outages.

The runtime has a pinned SHA-256 digest and Ed25519 signature verified by the launcher. These builds do not have Apple notarization or a Windows publisher certificate; operating systems may show an unidentified-publisher prompt. Linux needs a desktop browser and glibc 2.35 or newer. Measured launcher/runtime sizes are in each platform's manifest JSON.

Full archives remain on your selected drive. Manual job import and result-summary export work without portal storage. Automatic sync requires the Studio host's Upstash Redis integration. The paired-job contract currently uses 2026 and independent district teams. Existing live/CLI engine paths also support later years, shared-workforce coordination and connected utility networks.

Startup now shows progress immediately, preserves the launcher session on refresh, and waits for an authenticated local-server response before confirming success. **Open local engine** remains available if the browser did not open automatically. Each runner uses an available local port, so another service on port 8010 cannot silently block startup. Errors show the log location.
