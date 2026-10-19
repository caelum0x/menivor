# Desktop packaging

Ship Menivor artifacts for the native `reelforge-desktop` (GPUI/Rust) binary.
The stable bundle id remains `dev.reelforge.desktop`, version `0.1.0`.

Release packages must embed `ffmpeg` and `ffprobe`; they must not depend on the
customer's shell `PATH`. The FFmpeg build must include libass/the `ass` filter,
the timeline filters, and the H.264/AAC encoders. The shared release verifier
fails packaging when any capability is missing.

## macOS
```bash
cargo build --release -p reelforge-desktop
packaging/macos/bundle.sh --ffmpeg /absolute/ffmpeg --ffprobe /absolute/ffprobe
packaging/macos/bundle.sh --ffmpeg /absolute/ffmpeg --ffprobe /absolute/ffprobe \
  --sign "Developer ID Application: …"
```
`Info.plist` declares the camera / microphone / screen-capture usage strings the
OS shows when requesting permission; `entitlements.plist` grants the matching
hardened-runtime capabilities. `Menivor.icns` is generated from the locked brand
source by `scripts/generate-app-icons.sh` and copied into `Menivor.app`.
The bundler validates the media capabilities and rejects binaries linked to a
developer-machine package-manager prefix before copying them to
`Contents/Resources/bin/`.

## Linux
```bash
cargo build --release -p reelforge-desktop
# Stage reelforge-desktop, ffmpeg, and ffprobe in AppDir/usr/bin first.
packaging/verify-media-toolchain.sh \
  "$PWD/AppDir/usr/bin/ffmpeg" "$PWD/AppDir/usr/bin/ffprobe"
appimage-builder --recipe packaging/linux/AppImageBuilder.yml
```
`reelforge.desktop` is the freedesktop launcher entry.

## Windows
Place `ffmpeg.exe` and `ffprobe.exe` adjacent to `reelforge-desktop.exe`. Embed
`packaging/windows/reelforge.manifest` (PerMonitorV2 DPI + UTF-8 code page) and
`packaging/windows/Menivor.ico` into the executable at link time, then package
all three executables with your installer of choice. Validate the tool pair on
the Windows build host with `-filters`, `-encoders`, and `-version` before
signing the installer.

At runtime the resolver order is: absolute `MENIVOR_FFMPEG_PATH` /
`MENIVOR_FFPROBE_PATH` override, packaged location, then `PATH` for developer
builds. A present but invalid override fails closed and never falls through.

## Signed update channels

The mounted Settings updater supports stable and beta channels. Release builds
embed only the Ed25519 public trust root; the private key must remain outside
the repository and build hosts.

Configure a release build with:

```bash
MENIVOR_UPDATE_STABLE_URL=https://updates.example/stable.json \
MENIVOR_UPDATE_BETA_URL=https://updates.example/beta.json \
MENIVOR_UPDATE_KEY_ID=menivor-release-2026 \
MENIVOR_UPDATE_PUBLIC_KEY_BASE64=... \
cargo build --release -p reelforge-desktop
```

Generate a private key outside the repository and sign a manifest from real
package bytes:

```bash
openssl genpkey -algorithm ED25519 -out /secure/menivor-update.pem
python scripts/sign-desktop-update.py \
  --spec apps/desktop/packaging/update-spec.example.json \
  --private-key /secure/menivor-update.pem \
  --key-id menivor-release-2026 \
  --output target/release/stable.json
```

The signer computes artifact sizes and SHA-256 digests itself. The client
accepts only HTTPS manifests/artifacts, disables redirects, verifies the
detached Ed25519 signature over canonical release bytes, selects exactly one
platform/architecture artifact, rejects semantic-version downgrade/replay,
limits downloads to 1 GiB, stages with fsync + atomic rename, and rebinds
persisted staging metadata to the original signed manifest after restart.
macOS launches a verified PKG through `open`, Windows launches MSI through an
argument-safe `msiexec`, and Linux executes the verified staged AppImage.
