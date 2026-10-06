# emu: native macOS apps on iOS

emu is a demonstration of adapting a native macOS ARM64 application to iOS, so that its
original Apple silicon code runs on an iPhone. The working example is **your own Steam
copy of SnowRunner for macOS**. The game's machine code runs on the phone itself: nothing
is streamed from a Mac, and there is no JIT, no debugger and no jailbreak.

The tools target one exact SnowRunner build. They are not a general emulator, and other
applications need their own compatibility work. This repository contains no game files,
game binaries or shaders; everything comes from your own installation.

## Windows tool (local port, preview)

**No personal Mac required:** the new Windows desktop tool extracts and patches
the pinned ARM64 game libraries, assembles an unsigned IPA locally, and stages
verified resources for import through the iPhone Files picker. With no game files,
it can assemble a device diagnostic IPA from the public runtime alone.

The public iOS runtime is compiled once by the included GitHub Actions macOS
workflow, without an Apple account or game content. Windows signing/installation
uses an external sideloading tool. Windows `.exe` games are still unsupported.

- GUI source launcher: `emu-windows.cmd` (Python 3.10+).
- Portable EXE build: `python -m tools.freeze` (see build dependency instructions).
- Cloud workflow: `.github/workflows/windows-runtime.yml`, manually dispatched.
- Recommended download: **EmuWindows-starter** workflow artifact, containing the
  portable EXE, matching public runtime and unsigned device diagnostic IPA.
- [Windows 中文使用说明、当前验证状态](docs/WINDOWS-zh.md).

This port's cloud iOS compilation and Windows EXE build have passed. Its assembly
and resource logic also have structural fixture tests. The starter job runs the
frozen EXE with a real runtime to generate and validate a diagnostic IPA, with
Python removed from PATH and a Unicode output path. Actual game conversion,
iPhone behavior and sideloading still need device validation. The upstream device
results below describe the original Mac workflow.

Demo: [SnowRunner's Mac version running locally on an iPhone](https://www.reddit.com/r/EmulationOniOS/comments/1wpddpd/snowrunners_mac_version_running_locally_on_an/)

```
  On your Mac                                     On your iPhone
  -----------                                     --------------
  Steam: SnowRunner.app (read only)
     |  ./emu setup
     v
  build/  prepared copies  ---- ./emu install ---->  signed "SnowRunner" app
  game files (117, ~52 GB) ---- ./emu resources -->  app data container
                                (USB, resumable)
```

## Contents

- [Status](#status)
- [Requirements](#requirements)
- [Installation](#installation)
- [Everyday use](#everyday-use)
- [Touch controls](#touch-controls)
- [Commands](#commands)
- [How it works](#how-it-works)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Repository, license and third-party notices](#repository-license-and-third-party-notices)
- [Special sponsor](#special-sponsor)
- [Acknowledgements](#acknowledgements)

## Status

Upstream tested setup (not verification of the Windows port):

| Item | Version |
| --- | --- |
| Phone | iPhone Air, iOS 27 |
| Mac | Apple silicon, Xcode 27 |
| Game | SnowRunner for macOS from Steam, version 53.5 (111), Steam build 25096372 |
| Signing | free Apple ID ("Personal Team") |

Verified on that setup, starting from an empty app:

- installation, a full copy of all 118 resource files with every SHA-256 checked on the phone;
- a new game, the main menu, audio, the first map (Black River), driving and local saves;
- the touch overlay, including native HUD buttons such as AWD after using the pedals and steering;
- dismissing a Space-key tutorial window and returning to driving controls.

The first-map playtest is not a full playthrough. These areas still need testing or more work:

- every interaction with the game's own HUD, including refuelling and confirmation dialogs;
- hiding the driving controls while the truck functions panel is open (for now, use the eye
  button, see [Touch controls](#touch-controls));
- the gearbox (Low gear and similar): the game expects Left Shift held with mouse movement,
  and there is no touch control for that yet;
- maps other than Black River, DLC and game controllers.

## Requirements

- A Mac with Apple silicon and Xcode 27. Python 3 comes with Xcode's command line tools.
- SnowRunner for macOS installed through Steam, at the supported build above.
- Your Apple ID added in Xcode > Settings > Accounts. If you have no Apple Development
  certificate, create one under Manage Certificates. A free account was enough.
- An iPhone connected by cable, with Developer Mode on
  (Settings > Privacy & Security > Developer Mode), and **at least 55 GB free**
  (the game files take about 52 GB).

## Installation

Clone this repository and open its folder:

```sh
git clone https://github.com/brolnickij/emu.git
cd emu
```

For the supported SnowRunner build, the shortest first-run path on an Apple silicon Mac is:

```sh
./emu doctor
./emu start
```

`start` runs setup when needed, builds and installs the app, resumes the resource transfer, and launches the game. The separate commands below remain available for troubleshooting. A first transfer still needs about 52 GB of game files and can take half an hour or more. If iOS asks you to trust the developer certificate after installation, do so and rerun `start`; completed files will be skipped.

On Windows or Linux, `python emu inspect PATH` identifies a Windows `.exe` or reads a macOS `.app` version without Xcode. `python emu preflight --game PATH --full --report build/source-report.json` validates the original ARM64 binary hashes and all resource checksums using Python alone. Without `--full`, resources are checked by size only. Windows users can use `emu.cmd` instead of `python emu`.

Then check your setup and install the app:

```sh
./emu doctor      # 1. check Xcode, signing, the game and the phone (changes nothing)
./emu setup       # 2. save your settings, fetch SDL, prepare local copies
./emu install     # 3. build, sign and install the app
```

4. On the iPhone, trust your developer certificate if asked:
   Settings > General > VPN & Device Management > your Apple ID > Trust.

```sh
./emu resources   # 5. copy the game files: ~52 GB, half an hour or more over USB
./emu launch      # 6. start the game
```

`./emu setup` detects what it can and asks for the rest. You can also pass values:

```sh
./emu setup --team ABCDE12345 --bundle-id dev.yourname.emu.snowrunner
```

All settings live in one file, `config.local.json`. It stays on your Mac and is not committed.
If a copy stops halfway, run `./emu resources` again: it continues where it stopped.

## Everyday use

- **Start the game** with `./emu launch`, or tap the SnowRunner icon on the phone.
- **Every 7 days** a free-account signature expires. Run `./emu install` again. It reuses the
  prepared copies in `build/`, so it works even if Steam later updates or removes the Mac
  game. Do not delete `build/`.
- **Keep the team and `bundle_id`** from the first install. Updates keep your data only
  while they stay the same.
- **Back up before anything risky**: `./emu backup` copies saves and the touch layout to
  `build/backups/`. Return to the game's main menu first.
- **Never delete the app** unless you have a backup: iOS deletes the app's data container,
  which holds your saves and all 52 GB of game files.
- **Copied the files before** (for example with an older version of these tools)?
  `./emu resources --verify` checks them on the phone and records them as complete, without
  copying anything again.

## Touch controls

Tap the game's own menus and HUD buttons directly. The overlay follows the game screen:

| Screen | Overlay |
| --- | --- |
| Driving | Steering on the left, pedals and a camera stick on the right; Map, Actions and Space; pause |
| Map | Zoom in, zoom out and back; no driving controls |
| Menus and settings | Back and an optional keyboard |

- The **keyboard** button opens four arrows, Enter, Space and Back. Some tutorial windows
  ask for Space rather than Enter: use the key that matches the symbol the game shows.
- The **eye** button hides the whole overlay and brings it back, for example while the
  truck functions panel (Actions) is open.
- The **Space** button in driving mode acts as the keyboard Space key, including the handbrake.
- **Steering** starts at neutral wherever your thumb lands.
- To **move controls**, tap the four-arrow button in driving mode, drag them, then tap the
  checkmark. Positions are saved automatically; the reset button restores the defaults.

## Commands

| Command | What it does |
| --- | --- |
| `./emu doctor` | Checks tools, signing, the game files and the phone. Changes nothing. |
| `./emu inspect PATH` | Read-only input identification, also usable as `python emu inspect PATH` on Windows/Linux. |
| `./emu preflight --game PATH` | Portable source validation; `--full` hashes all resources and `--report PATH` saves results. |
| `./emu package-check PATH` | Portable verification of an IPA's structure and its adjacent JSON checksum receipt; does not validate Apple's signature. |
| `./emu toolkit` | Export the source toolkit as a ZIP, excluding game content and personal settings. |
| `./emu devices` | Lists connected iPhones. |
| `./emu start` | First-run workflow: setup if needed, build, install, transfer missing resources and launch. |
| `./emu setup` | Saves settings, downloads SDL, prepares local copies. No phone changes. |
| `./emu install` | Builds, signs and installs or updates the app. Data is kept. |
| `./emu resources` | Copies missing game files. `--dry-run` lists them, `--verify` checks files already on the phone. |
| `./emu launch` | Starts the game. `--diagnostics` writes extra logs. |
| `./emu run` | Checks the game files, then `install` and `launch`; for later updates. |
| `./emu backup` | Copies saves and the touch layout to `build/backups/`. |
| `./emu logs` | Copies app and game logs to `build/logs/`. |
| `./emu check` | Installs the app and tests graphics, input and touch without loading game code or files. |
| `./emu prepare`, `./emu build` | The individual steps behind `setup` and `install`. |
| `./emu package` | Build and export a locally signed app-only IPA plus a JSON checksum receipt to `build/exports/`. |

The IPA from `package` includes the prepared game libraries from your own copy but **not** the roughly 52 GB of game resources. Keep it private. Its development signature is tied to your provisioning and eligible devices; copying the IPA alone does not make the game playable. After installing it on a phone, use `./emu resources` with the same bundle ID and signing team. A free-account signature still expires after seven days.

For a detailed assessment of Windows-only operation, additional games and non-game apps, see [Architecture and packaging roadmap](docs/ROADMAP-zh.md).
For step-by-step Windows and Mac usage, see [Chinese quick start](docs/QUICKSTART-zh.md).

## How it works

### Inside the iPhone app

```
+--------------------------------- iPhone app process --------------------------------+
|  Host app (app/Host): loads the frameworks below, then calls the game's own main()  |
|                                                                                     |
|  GameClient (SnowRunner's ARM64 code, two calls changed)                            |
|    |-- SDL calls -------------------> SDLBridge ---> SDL 2.32.10 for iOS ---> UIKit  |
|    |-- AppKit, CoreGraphics, IOKit -> Compat* -----> MacCompat ---> UIKit / iOS      |
|    |-- Metal (original Mac shaders) -----------------------------> iOS Metal         |
|    |-- files ----------------------------------------------------> Documents/        |
|    `-- Steam API, EOS: loaded, Steam integration off                                |
+-------------------------------------------------------------------------------------+
```

The tested iOS 27 device accepted the game's original Mac Metal shader libraries without
conversion. The app requests the `increased-memory-limit` entitlement, which a free Personal
Team accepted on the tested device, and declares Game Mode support.

### Preparing the copies on the Mac

```
Steam install (read only)                                              build/Vendor/
lib_MR2_SpinTires.dylib --+
libEOSSDK-Mac-Shipping  --+-> validate -> retarget -> patch -> verify -> GameClient, EOS, SteamAPI
libsteam_api.dylib      --+
app/Compat sources ----------------------- clang --------------------> MacCompat, Compat*, SDLBridge
SDL 2.32.10 release + patches/sdl2-ios.patch -- xcodebuild -----------> SDL2
```

1. **Validate.** The ARM64 slice of each library must match a pinned SHA-256, both for the
   whole slice and for its `__text` machine-code section, and the app must be version
   53.5 (111). Anything else is refused before any output is written.
2. **Retarget (metadata only).** The Mach-O platform changes from macOS to iOS. macOS
   framework dependencies (AppKit, Carbon, CoreGraphics, IOKit, Foundation and others) point
   to small `Compat<Name>` frameworks, `libSystem` to `CompatSystem`, and the EOS and Steam
   API libraries to their prepared copies. The original signature is removed; Xcode signs
   everything with your team. EOS and the Steam API keep their machine code byte for byte.
3. **Patch the game library.** These are the only changes:

   | Change | Why |
   | --- | --- |
   | Byte strings naming the game's built-in Mac SDL classes (`SDL…`, `METAL_…`) become `SRM…`, `SRMTL_…` throughout the file | The game embeds a desktop SDL 2.26.4 whose Objective-C class names would clash with the real iOS SDL. The whole-file replacement is safe only because the input is pinned by its full hash. |
   | Config key `steam.enabled` renamed to `ios.no_steam_` | The retail config can no longer switch Steam on, so the setting keeps its built-in default: off. |
   | Call at `0xdb5800` goes to another save factory | Saves use the game's local-file storage instead of Steam storage. |
   | Call at `0x39d568` goes to another mod provider | Uses the game's own offline mod.io provider. `Mods.enabled` stays on, because turning it off broke the UI. |

   Each instruction is compared with the expected old word before anything is written.
   Nothing signs a user in, grants a license or unlocks DLC.
4. **Verify.** The result must match the pinned SHA-256 of the prepared file and of its
   machine code. All pins are in `data/supported-game.json`.

Prepared game libraries are reused while their full SHA-256 matches the pin. The adapters
are rebuilt when their sources, the tools, the data files, the SDL patch, Xcode or the iOS SDK
change. That is why `./emu install` can re-sign the app without the Mac game.

### Adapters (`app/Compat`)

- **SDLBridge.** The game's built-in SDL supports SDL's dynamic API: when `SDL_DYNAMIC_API`
  names a library, every SDL call goes through that library's function table. SDLBridge fills
  the exact 833-entry table of SDL 2.26.4 (`SDL2264Indices.h`, `SDL2264Names.inc`) with the
  native iOS SDL 2.32.10 and wraps a few entries: raw finger events are dropped (iOS SDL
  already turns touches into mouse events), the window joins the active window scene, the
  base path points at the copied game files, and mouse and keyboard state are adapted as
  described below.
- **MacCompat.** Real implementations of what the tested path needs: display information
  from `UIScreen` with lower render sizes, an `NSApp` stand-in, game-controlled Metal
  drawable size, a description of the built-in GPU, and file calls passed straight through
  (failures logged only in diagnostics mode).
- **Fail-fast stubs.** Other imported macOS functions are listed in
  `data/desktop-symbols.json`. Each becomes a function that stops the app and logs
  `UNIMPLEMENTED <name>` with its caller. String constants use the values recorded in
  that file. Unimplemented functions do not return a fake success.
- **Compat\<Name\>.** Empty frameworks that re-export MacCompat and the matching iOS
  frameworks, so the game's dependency list stays recognizable.

### Touch input

SnowRunner reads mouse buttons and gameplay keys by polling their state once per frame; it
ignores SDL mouse-button events. It also switches its HUD between mouse and gamepad modes
depending on which input device changed most recently. The overlay's driving controls are a
virtual SDL gamepad (reported as an Xbox 360 controller), so a finger tap has to hand the
focus back to the mouse before the HUD will accept it:

```
finger down/up
   -> hover frames: pointer at the tap position, button still up
      (if the game's input focus is on the gamepad: one balanced +1/-1 mouse movement,
       then wait until gsINPUT_SYSTEM::IsControlledByGamepad() reports mouse/keyboard)
   -> pressed frame -> released frame
```

- Each tap keeps its own position in a small queue; held touches keep dragging.
- The wait for mouse focus is bounded; a timeout is logged in diagnostics mode.
- Touch camera movement is suppressed while driving; the camera stick is separate.
- Overlay key releases wait until a later frame after the first keyboard-state read.
  Both the UI and gameplay poll the keyboard, so a UI read must not release a quick tap
  before gameplay sees it.
- `GameContext.c` reads the game's own map, pause and truck-control state through exported
  functions to choose the overlay (menu > map > pause > driving). One read-only member,
  `GameSsl + 0x79`, distinguishes an in-game menu from the map; its writer and reader were
  checked in the pinned binary. Held inputs are released whenever the screen changes.
- A physical mouse, if connected, bypasses all of this.

### Copying game files safely

```
for each missing file:
   remove its completion record on the phone
   copy the file                          (USB, may be interrupted)
   check its size on the phone
   add its completion record              (only now does it count as done)
```

A file counts as done only with the right size **and** a record in
`Documents/emu-resources.json`. If the record file is damaged, copying stops;
`./emu resources --verify` rebuilds it by hashing the files on the phone. Source files on the
Mac are hashed before copying (cached by path, size and modification time).

### The host app's modes

| Mode | Used by | What it does |
| --- | --- | --- |
| game (default, also the Home Screen icon) | `./emu launch` | Checks the game files, then starts the game |
| maintenance | `./emu resources` | Creates folders, reports free space, stays idle while files are copied |
| verify-resources | `./emu resources --verify` | Hashes the files on the phone and writes completion records |
| check | `./emu check` | SDL, Metal, touch and input self-test without game files |

### Files in the app container

| Path | Contents |
| --- | --- |
| `Documents/SnowRunner/SnowRunner.app/Contents/Resources/` | Game files |
| `Documents/SnowRunner/sandbox/base/storage/` | Saves and game settings |
| `Documents/SnowRunner/sandbox/base/logs/` | The game's own logs |
| `Documents/touch-controls-layout.plist` | Touch control positions |
| `Documents/emu-resources.json` | Completion records for copied files |
| `Documents/guest-load.log`, `guest-console.log` | Start-up stages and game output |

## Limitations

- Steam is off: no Steam Cloud, achievements, friends or multiplayer. Nothing pretends to be
  signed in and DLC ownership is not faked; DLC availability has not been tested.
- Saves exist only on the phone and do not sync with the Mac or Steam Cloud.
- All installed map files are copied, but only Black River has been played.
- macOS functions outside the tested path are not implemented. If the game needs one, it
  stops on purpose and logs the name.
- The gearbox needs Left Shift and mouse movement, which the overlay does not provide yet.
- Driving controls do not automatically hide for the truck functions panel; use the eye button.
- Performance, heat and battery use have not been measured systematically.
- Another game build needs new pins and a new review of every change.

## Troubleshooting

Start with `./emu doctor`, then reproduce with `./emu launch --diagnostics` and collect
logs with `./emu logs`.

| Problem | What to do |
| --- | --- |
| "Unsupported SnowRunner version" or "Unsupported … ARM64 binary" | Steam has probably updated the game. The changes depend on exact byte positions, so another build is refused. An installed app keeps working, and `./emu install` can still re-sign it from `build/`. |
| The game is not found | `./emu setup --game "/path/to/SnowRunner.app"`. Steam's default is `~/Library/Application Support/Steam/steamapps/common/SnowRunner/SnowRunner.app`. |
| SDL download or checksum fails | Check the network and run `./emu setup` again. A file with the wrong checksum is never used. |
| No signing team or profile, "failed to register bundle identifier" | Add your Apple ID in Xcode and create an Apple Development certificate, then `./emu setup --team <TEAM ID>`. Choose your own unique `bundle_id`. Free accounts hold only a few development apps; remove unused ones. |
| Installation refused after changing the team | Do not delete the app. Put the previous team back in `config.local.json` and run `./emu install`. If you must change it, run `./emu backup` first. |
| "Untrusted Developer" | Settings > General > VPN & Device Management > your Apple ID > Trust. |
| The phone is not listed | Connect by cable, unlock it, accept "Trust This Computer", enable Developer Mode and restart the phone. |
| The app stopped opening after a week | The free signature expired. Run `./emu install`; saves and game files stay. |
| Game files missing or unverified | `./emu resources`, or `./emu resources --verify` for files copied earlier. |
| "Resource completion records are damaged" | `./emu resources --verify` rebuilds them without copying. |
| "Not enough free space" | The game files need about 52 GB; keep at least 55 GB free. |
| The copy is slow | About 35 MB/s was observed over USB. Keep the phone unlocked on the "Ready to transfer" screen. |
| The app closes and `guest-load.log` shows `UNIMPLEMENTED <name>` | The game needed a macOS function that is not implemented. Please report the line; it names the caller. |
| The app closes without `UNIMPLEMENTED` | Check `guest-console.log` and the crash reports in Xcode > Window > Devices and Simulators. `--diagnostics` also records memory use. |
| Wrong controls shown, or a HUD tap moves the camera | Reproduce with `--diagnostics`, then `./emu logs`, and note the screen and button. The eye button hides the overlay meanwhile. |
| Another map or DLC misbehaves | Only Black River has been tested. Please report it with `./emu logs`. |

`./emu check` tests the platform without the game: SDL window, Metal frame, events, touch
layout and the virtual gamepad. Results go to `build/reports/sdl-check.json`.

## Repository, license and third-party notices

The repository holds source code, patches and metadata only: file names, sizes and SHA-256
pins used to validate your own copy. It contains no game files, game binaries, shaders,
credentials or device identifiers. `build/`, `config.local.json` and `Config/Local.xcconfig`
stay on your Mac and are ignored by Git.

- **Our code** is MIT licensed, see [LICENSE](LICENSE).
- **SDL.** `app/Compat/SDL2264Indices.h` and `app/Compat/SDL2264Names.inc` list the order and
  names of the SDL 2.26.4 dynamic API table. `patches/sdl2-ios.patch` changes five SDL
  2.32.10 source files (UIKit window-scene geometry and the export of
  `SDL_SendVirtualKeyboardKey`) and contains SDL source lines as context. `./emu setup`
  downloads SDL 2.32.10 from its
  [official release](https://github.com/libsdl-org/SDL/releases/tag/release-2.32.10)
  (URL and SHA-256 in `data/sdl.json`), applies the patch and builds it locally. This is a
  modified version of SDL. SDL is by Sam Lantinga and contributors, under the zlib license:
  [third_party/SDL-LICENSE.txt](third_party/SDL-LICENSE.txt). The license text is also
  included in the app.
- **From your own installation, never included:** the SnowRunner game library
  (`lib_MR2_SpinTires.dylib`) and all game resources, `libEOSSDK-Mac-Shipping.dylib`
  (Epic Online Services SDK) and `libsteam_api.dylib` (Steamworks API), both shipped with the
  game. They are proprietary software of their owners and are prepared and signed locally.
- **Apple SDKs.** The app links against system frameworks from the iOS SDK in Xcode; no SDK
  files are included. `data/desktop-symbols.json` lists macOS symbol names the game imports
  and the values of some string constants.

SnowRunner, Steam and the Epic Online Services SDK belong to their respective owners. This
project is not affiliated with or endorsed by them.

## Special sponsor

[Cutio — AI Sponsor Skipper](https://chromewebstore.google.com/detail/cutio-ai-sponsor-skipper/maobicegceffhejjnpjjggnpopmanplg),
a browser extension made by the author of this project.

## Acknowledgements

A huge thank you to **GPT-6 Astra** and **Claude Opus 5.5**, who worked as a pair on this
project: researching the game's machine code, building the adapters and tools, debugging
input on a real phone, and checking each other's conclusions. Their work, alongside many
rounds of hands-on testing, turned this experiment into SnowRunner running locally on an
iPhone.
