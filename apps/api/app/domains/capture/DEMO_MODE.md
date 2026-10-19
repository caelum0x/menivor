# Capture: native game recording and demo mode (v2)

Our games are native mobile apps (Expo). Menivor does not capture web games.
Gameplay is recorded from an iOS Simulator or an Android emulator that runs the
game on the capture host. Website and store-listing captures are unchanged.

Web game capture (`web_game`, the v1 `window.__menivorDemo` browser hook) was
removed. Old `web_game` rows still load in the capture list and detail pages,
but they cannot be retried.

## How a native capture runs

`POST /api/v1/capture` with `kind: "native_game"`:

```json
{
  "kind": "native_game",
  "formats": ["9:16"],
  "duration_s": 30,
  "native": {
    "platform": "ios",
    "device": "booted",
    "app_id": "com.example.flowblast",
    "deep_link": "flowblast://play?menivor_demo=1&seed=7",
    "title": "FlowBlast",
    "settle_s": 4
  }
}
```

| Field | Meaning |
| --- | --- |
| `platform` | `ios` (Simulator) or `android` (emulator). |
| `device` | iOS: a simulator UDID or `booted` (the default). Android: the adb serial, for example `emulator-5554`. Required on Android. |
| `app_id` | Bundle id (iOS) or package name (Android). Launches the game when there is no deep link. |
| `deep_link` | Optional. Opens the game, ideally straight into demo mode (see below). |
| `title` | Game name used in the drafted ad script. |
| `settle_s` | Seconds to wait after launch before recording starts (0 to 30, default 4). |

The steps, in order:

1. The game is brought to the foreground. With a deep link, iOS runs
   `xcrun simctl openurl <device> <link>` and Android runs
   `adb -s <serial> shell am start -W -a android.intent.action.VIEW -d '<link>' [-p <package>]`.
   Without a link, iOS runs `xcrun simctl launch --terminate-running-process <device> <bundle>`
   and Android runs `adb -s <serial> shell monkey -p <package> -c android.intent.category.LAUNCHER 1`.
   With neither, the operator has already launched the game and it is recorded as it is.
2. Menivor waits `settle_s` seconds.
3. Recording runs for `duration_s` seconds (10 to 60, default 30).
   * iOS: `xcrun simctl io <device> recordVideo --codec=h264 --force <file>`,
     stopped with SIGINT. One still is taken halfway through with
     `simctl io screenshot`.
   * Android: `adb shell screenrecord --time-limit <s> /sdcard/menivor-<id>.mp4`,
     then `adb pull` and `adb shell rm`. One still is taken with
     `adb exec-out screencap -p`.
4. The recording is encoded once per requested format: 1080x1920, 1920x1080
   or 1080x1080 H.264 at 30 fps with a silent audio track. The phone screen is
   padded to fit, and the video then feeds the reel pipeline like any other
   capture.

The job's `metadata.capture_mode` is `native_ios` or `native_android`.

## Demo mode for our games (recommended)

Scripted inputs are not sent to native games. For a good-looking run, give
the game a deep link that starts a self-playing session. The link can open an
AI player, a recorded replay or an attract loop.

Convention (v2):

```
<scheme>://play?menivor_demo=1&seed=<n>
```

When the game opens with `menivor_demo=1`, it should:

* skip onboarding, login, consent and purchase prompts, and hide debug overlays;
* start gameplay within a couple of seconds (keep `settle_s` above that time);
* use `seed` so the same capture gives the same run;
* keep playing for at least 60 seconds, the longest recording.

Expo example with `expo-linking` and `expo-router`:

```ts
// app/play.tsx
import { useLocalSearchParams } from "expo-router";

export default function Play() {
  const { menivor_demo, seed } = useLocalSearchParams<{ menivor_demo?: string; seed?: string }>();
  const demo = menivor_demo === "1";
  return <Game autoplay={demo} seed={demo ? Number(seed ?? 1) : undefined} hideMenus={demo} />;
}
```

Register the scheme in `app.json` (`"scheme": "flowblast"`). A development
or release build must be installed on the simulator or emulator; Expo Go
cannot handle custom schemes.

## Operator setup

Native game capture is off by default. It runs on the capture host: the API
process when `capture_executor = "inline"`, or the render-queue Celery worker
when it is `"celery"`. Enable it only on a machine that has the tooling and
a booted device:

```toml
[app]
capture_native_game = true
# Optional allowlist. When set, only these bundle ids / package names can be
# captured, and every request must name one.
capture_native_app_ids = ["com.example.flowblast"]
```

* iOS needs macOS with Xcode command line tools (`xcrun simctl`), a booted
  simulator (`xcrun simctl boot <udid>`) and the game installed
  (`xcrun simctl install <udid> <App.app>`).
* Android needs the platform tools (`adb`) on `PATH`, a running emulator
  (`emulator -avd <name>`) and the game installed (`adb install app.apk`).
  `screenrecord` caps a single recording at 180 seconds.

Only one recording runs per device at a time within a process. If two
workers share a device, give each worker its own simulator or emulator.

Every device id, app id and deep link is checked against a strict pattern.
Commands run as argument lists without a local shell. The Android deep link
is also shell-quoted, because `adb shell` passes it through the device's
shell.

Website captures still need Playwright and a headless Chromium:

```bash
pip install -r requirements.txt            # includes playwright
python -m playwright install --with-deps chromium   # ~150 MB browser download
```

App Store, Google Play and native game captures do not use the browser. They
need ffmpeg, which is already required.
