# Third-party components

Everything listed here belongs to someone else. Infomac Solutions claims no
copyright in any of it, and nothing in `LICENSE` restricts any right granted by
the licences below. Where a file is covered both by one of these and by
`LICENSE`, the licence named here governs that file.

## The platform this is built on

**Traccar** — Anton Tananaev — Apache License 2.0
Licence text: [`LICENSE.txt`](LICENSE.txt) · https://github.com/traccar/traccar

This repository is a fork of Traccar. The server under `src/`, the web app
under `traccar-web/` and the mobile shell under `traccar-manager/` are Traccar's
work except where a file carries an Infomac Solutions copyright header. Files
modified for DH FleetView remain derivative works of Traccar and stay under the
Apache licence; the modifications are the Owner's.

Upstream releases are tracked rather than merged wholesale — see
[`UPSTREAM.md`](UPSTREAM.md) and `.github/workflows/traccar-upstream-watch.yml`.

## Bundled and vendored

| Component | Where | Owner / licence |
|---|---|---|
| **Tacho Bridge App** | `tacho-bridge-app/` | A fork of the upstream project, kept close to it. Its own licence applies; see that directory. |
| **Jessibuca player and its ffmpeg/wasm decoder** | `traccar-web/public/gpsplayer/` | Vendored runtime (`libffmpeg.js`, `libffmpeg.wasm`, `decoder.js`, `pcm-player.js` and siblings). Not ours; shipped as supplied. |
| **win-acme** | `tools/win-acme/` | ACME client for the TLS certificate. Its own licence applies. |
| **ffmpeg** | `tools/ffmpeg.exe` | FFmpeg project. GPL/LGPL depending on build; see the FFmpeg project's terms. |
| **npm packages** | `node_modules/`, `traccar-web/node_modules/` | Each package under its own licence as declared in its `package.json`. |
| **Gradle wrapper** | `gradle/wrapper/` | Gradle, Apache License 2.0. |

## Depended on at run time, not in this repository

| Component | Licence | Note |
|---|---|---|
| **traconiq/tachoparser** | **AGPL-3.0** | Reads driver cards and vehicle units. Invoked as a separate executable over stdin/stdout — nothing from it is imported, linked or vendored — so the AGPL's copyleft does not reach this source. Its network clause still obliges offering tachoparser's own source to anyone interacting with it; the build tree and a `PROVENANCE.txt` naming the commit are kept beside the binary on the server. **This one is worth a solicitor's eye before the platform is resold.** |
| **way-platform/tachograph-go** | MIT | Second tachograph reader, kept as a fallback. Imposes nothing. |
| **CNMS / CMSV9** | Vendor's terms | The video platform the cameras talk to. |
| **Kokoro, edge-tts, Whisper** | Their own terms | Used by tooling, not shipped in the product. |

## Fonts and media

Any font or image not listed above and not carrying an Infomac Solutions header
is either Traccar's or the supplier's, under its own terms.

---

If you add a dependency, vendor a library, or copy code in from anywhere, add it
here in the same change. A proprietary claim that quietly sweeps in other
people's work is worse than no claim at all — it is both a licence breach and
the first thing a buyer's solicitor will find.
