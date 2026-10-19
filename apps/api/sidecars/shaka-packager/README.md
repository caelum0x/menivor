# shaka-packager sidecar (Wave P PM2.4, MV3)

- Upstream: https://github.com/shaka-project/shaka-packager, licence BSD-3-Clause (LICENSE file;
  the GitHub API reports NOASSERTION). Run unmodified as a binary; no source is vendored.
- Pinned: `VERSION` (v3.9.3). `SHA256SUMS` holds the release digests read with `gh api` on
  2026-09-30 (the osx-arm64 build was also downloaded and hashed locally for the tests).
- The binary is not committed. `fetch.sh linux-arm64 /usr/local/bin/packager` downloads it and
  refuses it unless the checksum matches; the worker image runs it at build time and the
  worker verifies it again at start (`app/services/ott_package/packager.py::verify_binary`).
- Env: `SHAKA_PACKAGER_BIN` (default `/usr/local/bin/packager`), `SHAKA_PACKAGER_PLATFORM`
  (default `linux-arm64`).
