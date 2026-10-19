# ReelForge Desktop

Built with [GPUI](https://www.gpui.rs).

The GPUI desktop client is a generation workspace: configure an API base and
personal API key, submit avatar-reel and AI B-roll jobs, monitor their shared
states, generate image or video through the unified media gateway, and preview
completed results. The media workspace accepts an optional source-image URL for
image-to-video models and polls video jobs on the background worker. API keys are deliberately kept out of
preferences and stored only through the operating-system credential store.

The wallet panel supports personal/workspace Mint transfers with saved
recipients, server-sealed review, exact idempotent retry and sender-owned
recovery. Source selection loads its own authoritative balance; late responses
from an old selection are ignored, and a workspace send never rewrites the
personal media balance. Each source exposes a stable `ait1…` receive address,
and reviewed sends accept either a person handle or an exact personal/workspace
address without exposing internal Mint account ids.

The API base URL is the only persisted setting and is normalized to
`…/api/v1`. It is written atomically to the operating-system configuration
directory (`Library/Application Support` on macOS, `%APPDATA%` on Windows, or
`$XDG_CONFIG_HOME` / `~/.config` on Linux). The API key never appears there.
Credential and filesystem operations run on the workspace worker rather than
the GPUI render thread.

## Architecture

```text
src/app.rs                 application/window composition
src/api/                   typed HTTP, auth, reels, B-roll, uploads, polling
src/config/                non-secret preferences and capability snapshots
src/security/              macOS/Windows/Linux credential-store adapters
src/domain/                reel, B-roll, job, and library models
src/workspace/             commands, reducer, persistence, background worker
src/media/                 native file selection/probing/preview launch
src/ui/                    GPUI shell, feature actions, views, and components
src/telemetry/             client event vocabulary
```

The GPUI shell sends immutable commands to one background owner of HTTP,
polling, uploads, secure credentials, and local persistence. Worker updates are
reduced into UI snapshots. The desktop calls only the canonical `/api/v1/jobs`
and `/api/v1/generation/broll/*` product contracts; it never imports backend
engine code. Direct uploads use the same presign → R2 PUT → ownership-register
handshake as web and mobile. `electron-legacy/` is frozen migration reference and is excluded
from active desktop development and packaging.

## Running

Native packaging uses the locked Menivor mark under `packaging/`: ICNS for
macOS, ICO for Windows, and PNG for Linux. Regenerate them together with the
Expo assets via `../../scripts/generate-app-icons.sh`; internal binary and
bundle identifiers remain stable for compatibility.

Rust is pinned in `.prototools` at the repo root (`proto use` installs it).

```sh
moon run desktop:dev     # cargo run
moon run desktop:check   # cargo check
moon run desktop:build   # cargo build --release
```

On a macOS host without the optional offline Metal compiler, application code
and tests can still be checked using GPUI's runtime-shader feature:

```sh
cargo check -p reelforge-desktop --features gpui/runtime_shaders
cargo test -p reelforge-desktop --features gpui/runtime_shaders
```

The first build compiles GPUI from source and takes a while. The root `Cargo.lock` is committed.

Release packages embed `ffmpeg` and `ffprobe`; developer builds may fall back to
`PATH`. Absolute `MENIVOR_FFMPEG_PATH` and `MENIVOR_FFPROBE_PATH` overrides take
priority and fail closed when invalid. Ordered trims, 0.25×–4× video/audio speed changes, concatenation, and
silent inputs work with the standard filters. Burning segment captions or text
overlays requires an FFmpeg build compiled with libass (the `ass` filter); the
desktop checks this capability before starting and reports the missing feature
without publishing a partial output.

The Editor's local-source action probes duration and decodes a bounded 100 Hz
mono analysis stream into 120 normalized waveform peaks on the background
worker. The selected file is hashed before and after analysis. Local render
refuses changed bytes and segment endpoints beyond the measured duration, so the
preview and rendered EDL cannot silently refer to different source content.

Settings also mounts the native signed updater. Stable/beta checks, semantic
version and replay protection, Ed25519 manifest verification, exact target
selection, bounded download, SHA-256 verification, restart-safe staging, and
platform installer launch run on the background worker. Builds without the
compile-time update URLs and public trust root fail the check explicitly; they
never accept an unsigned fallback.

## Platform requirements

- **macOS**: Xcode command line tools (Metal renderer). API keys use the login Keychain.
- **Windows**: no extra dependencies (Win32 + DirectWrite). API keys use Windows Credential Locker; saving is blocked if it is unavailable.
- **Linux**: renders via Vulkan (Blade), windows via Wayland or X11 (both enabled by default). System packages (Debian/Ubuntu names): `libvulkan1` + working Vulkan drivers, `libwayland-dev`, `libx11-xcb-dev`, `libxkbcommon-x11-dev`, `libfontconfig-dev`, plus a C toolchain and `cmake`. Install `libsecret-tools` (for `secret-tool`) and run a Secret Service provider such as GNOME Keyring or KWallet; saving is blocked when the service is unavailable.
- **WSL2/WSLg**: uses XWayland automatically when available. GPUI 0.2.2 requires `xdg_wm_base` v2–5, while WSLg advertises v1.
