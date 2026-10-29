# RTX4060 Ka-chow!

Named after Lightning McQueen, whose portrait is the default start-screen banner.

Unlocks the half-rate FP16/BF16 (FP32 accumulate) and TF32 tensor-core throttle on the
GeForce RTX 4060 Laptop GPU (AD107, `10de:28a0`) **with Secure Boot left on**.

A Microsoft-signed [shim](https://github.com/rhboot/shim) chain-loads a MOK-signed,
patched build of [NekoMirra's UEFI unlocker](https://github.com/NekoMirra/rtx4060-laptop-tensor-unlock),
which writes the rate selectors (`SS0=0x88888888`, `SS1=0x8`) before Windows starts.
No EV certificate, no test signing, no Secure Boot toggle.

Measured on an Acer Nitro AN515-58 (discrete-GPU mode, driver 610.62, 8192³ GEMM,
best of 3; raw output in [docs/results](docs/results)):

| Mode | Locked | Unlocked (automatic build) | Gain |
|---|---|---|---|
| FP16, FP32 accumulate | 29.6 TFLOPS (0.60) | 45.5 TFLOPS (1.00) | +54% |
| BF16, FP32 accumulate | 30.2 TFLOPS (0.61) | 46.9 TFLOPS (1.02) | +55% |
| TF32 | 14.7 TFLOPS (0.30) | 22.6 TFLOPS (0.49) | +54% |
| FP16, FP16 accumulate (reference) | 49.1 TFLOPS | 45.7 TFLOPS | never throttled |

The figures in brackets are ratios to the FP16-accumulate reference measured in the same
pass, not the gain; the gain column compares the raw TFLOPS.

## Before you start

- **Hardware:** a laptop with exactly one GeForce RTX 4060 Laptop GPU (`10de:28a0`). Any
  other card is refused before the unlocker touches it. Tested on one Acer Nitro AN515-58
  only (see [Limits](#limits)).
- **System:** Windows (tested on Windows 11) booting in UEFI mode, with Secure Boot on and the Microsoft UEFI
  CA trusted (the default on most laptops), and an administrator account.
- **Tools:** Python 3.11+, OpenSSL and Git to build; torch with CUDA only for the benchmark.
- **BitLocker:** have the recovery key at hand. `install` shows it and suspends BitLocker
  for the boots that change the boot chain.
- **Risk:** this runs code before Windows and changes GPU settings that NVIDIA locks. It is
  provided as is, without warranty (GPL-2.0, sections 11-12). Read [Recovery](#recovery)
  before installing.

Clone it inside your own user profile, not at the top of a drive: a folder like `C:\src`
lets every local account change the scripts that `install` then runs elevated.

```powershell
cd $env:USERPROFILE
git clone https://github.com/st0nebridge/RTX4060-Kachow.git
cd RTX4060-Kachow
```

Then set up `local/` ([Setting up `local/`](#setting-up-local)), build and test, and install.

## The unlock needs a power-on

**Shut down, Restart or Hibernate → the unlocker runs and Windows starts (or resumes)
unlocked.** Fast Startup can stay on: a Fast Startup shutdown and a hibernate both power
the machine off, so the firmware starts the unlocker before Windows resumes. Measured on
2026-10-29: two Fast Startup boots (RUN0024, RUN0025; Windows boot type 0x1) and a
hibernate resume (RUN0026; type 0x2) all unlocked, with 46.0–46.1 TFLOPS FP16/FP32
accumulate afterwards.

A Restart runs the firmware boot too. With the automatic build the last four restarts in
a row unlocked: RUN0022 and RUN0023 (Start menu), RUN0027 (a NitroSense mode switch) and
RUN0030 (`shutdown /r`). The one failure was the first restart on that build, RUN0019 on
2026-10-28, whose log ends just after the GPU reset; the cause is not known. RUN0016
(STOP) ran the earlier manual build, which stopped after a Shut down too (RUN0015), so it
says nothing about Restart. If a restart ever starts Windows without the unlock, Shut down
and power on.

Sleep, a driver reload or a runtime power-off (D3) lose the unlock. Waking from Sleep (S3
on the AN515-58) does not run the firmware boot, so the unlocker cannot run; that is
expected, not yet measured.

- `.\bin\read-log.ps1` says what happened during the last boot (`status=unlocked`).
- `.\bin\bench.ps1` says whether the unlock is still active now (`UNLOCKED`).

## Hybrid (Optimus) mode

On the AN515-58 the GPU mode is set in NitroSense, which restarts to apply it. In hybrid
mode the unlock completes before Windows as it does in discrete mode, but the NVIDIA
driver powers an idle RTX off, and the power-off resets it. So after the first unlock
`kachow.ps1` adds a **keeper**: a startup task (SYSTEM, before logon) that runs
`bin\keeper.ps1`, which holds a CUDA context on the RTX and writes 1 MiB to it every
second, so the driver never sees it idle. Measured on 2026-10-29 in hybrid mode:

| Boot | Keeper | RTX | FP16, FP32 accumulate |
|---|---|---|---|
| RUN0027, HDMI monitor attached | holding from 125 s | D0 throughout | 47.5 TFLOPS, UNLOCKED |
| RUN0028, no external monitor | holding from 125 s | D0 throughout | 47.3 TFLOPS, UNLOCKED |
| the same boot, keeper stopped | none | D3 within 1 s, for 76 s | 30.2 TFLOPS, LOCKED |
| RUN0029, the installed keeper | holding from 130 s | D3 at the keeper's start, then D0 | 45.1 TFLOPS, UNLOCKED |
| RUN0030, the installed keeper | holding from 23 s | D3 at the keeper's start, then D0 | 45.9 TFLOPS, UNLOCKED |

- The RTX stays powered for the whole session: about 2 W at idle (P8, 210 MHz).
- The keeper starts when Windows runs startup tasks, about 23 s after power-on on this
  laptop; a slow boot leaves the RTX longer at D3 before the keeper holds it. A D3 before
  then does not always reset the unlock: in RUN0029 and RUN0030 the RTX was at D3
  when the keeper started and stayed unlocked, while 76 s at D3 in RUN0028 reset it. The
  reading does not tell a powered D3 from a power cut, so when the keeper's start line in
  `local\logs\keeper.log` reads `RTX=D3`, `status` and the guard say the unlock may have
  been reset and `bench.ps1` gives the answer. An earlier test without the keeper found
  the RTX off at 120 s and the unlock gone.
- If the keeper stops, the RTX powers off within a second and the unlock is gone until
  the next power-on. The task restarts the keeper, but that cannot bring the unlock back.
- The keeper also runs in discrete mode, where it changes nothing (the RTX drives the
  panel and is never powered off), so switching modes needs no reinstall.
- Not yet measured in hybrid mode: Fast Startup and hibernate (the keeper is suspended
  with the session rather than started again).

## How it works

```
Firmware (Secure Boot db: Microsoft UEFI CA)
  └─► \EFI\tensor-unlock\shimx64.efi        Ubuntu shim 15.8, Microsoft-signed
        ├─► grubx64.efi                      patched unlocker, MOK-signed, carries .sbat
        │     ├─ maps BAR0, runs FWSEC, writes SS0/SS1, FLR, reconnects the display
        │     ├─ logs to \GPU4090-UNLOCK\RUNnnnn.TXT
        │     └─ LoadImage(\EFI\Microsoft\Boot\bootmgfw.efi) ─► Windows
        └─► mmx64.efi                        MokManager: key enrollment, first boot only
```

Upstream ships unsigned images that refuse Secure Boot, and its display checks did not
expect this firmware's console splitter. [patches/secureboot-shim.patch](patches/secureboot-shim.patch)
changes two files:

- `app.c`: when the firmware reports Secure Boot on, continue only when shim's SHIM_LOCK
  protocol is present, i.e. the image was started through shim. That check alone does
  not prove the image was verified: shim installs the protocol even when its own
  validation is turned off (MokSBState, `mokutil --disable-validation`). In the
  installation below validation stays on, so shim verifies the MOK signature before it
  starts the unlocker. The boot log's "MOK-verified image" line reads more into the
  check than it proves.
- `release.c`: a GOP without a device path (the console splitter) is accepted only when
  it mirrors a GOP that has a PCI path, or, after the RTX display driver is stopped, when
  it still shows a screen the RTX driver owned at preflight. Any other unmatched GOP
  still refuses. Every GOP is logged (`diag:` lines).

The unlock is volatile; see [The unlock needs a power-on](#the-unlock-needs-a-power-on).

## Layout

```
bin/            entrypoints
  kachow.ps1      install | uninstall | status | recover, in one command each (see Install)
  kachow.py       Python dispatcher: python -I bin/kachow.py <command> (--help)
  keeper.ps1      run by the keeper task at startup: keeps the RTX powered (hybrid mode)
  build.ps1       build gate: pinned source + patches → zig → hash check → .sbat → MOK signature
  test.ps1        test gate: pytest + coverage, PowerShell parse + preflight
  mutate.ps1      mutation pass (cosmic-ray), sandboxed; -Modules for a few files
  deploy.ps1      swap the unlocker variant on an installed ESP (also refreshes the banner)
  banner.ps1      put config/banner.txt on the start screen (no rebuild)
  read-log.ps1    show the newest boot log and whether that boot unlocked
  bench.ps1       is the unlock active right now?
  d3hot.ps1       kept for the record, not applied (see docs/history.md)
src/kachow/       pe, sbat, signature, zigbuild, mok, runlog, lifecycle, keeper, manifest, banner, bench/{gemm,verdict}, cli
src/windows/      Project, Runtime, Esp, FirmwareVars, Signing, Banner, Install, Machine (.psm1, shared by bin/*.ps1)
config/           banner.txt: the start-screen art (edit freely; Lightning McQueen by default)
patches/          source patches against the pinned upstream commit, applied in manifest order
third_party/      manifest.json: upstream commit, download URLs and SHA-256 of every binary
tests/            unit/, regression/ (one per fixed fault), integration/ (PowerShell), fixtures/
docs/             history.md (how the boot chain was made to work), results/ (benchmarks)
local/            machine state, never committed (see below)
```

## Setting up `local/`

`local/` is gitignored. It holds the signing key, third-party binaries and state:

| Path | What | How to get it |
|---|---|---|
| `keys/MOK.key`, `MOK.pem`, `MOK.cer`, `MOK.pfx` | your Machine Owner Key | see below; **keep private**: `MOK.key` and `MOK.pfx` are made readable by Administrators and SYSTEM only, so signing runs elevated |
| `efi/shimx64.efi`, `efi/mmx64.efi` | shim 15.8 and MokManager | `usr/lib/shim/shimx64.efi.dualsigned` and `mmx64.efi` from the `shim-signed` .deb in the manifest |
| `assets/*.bin`, `assets/NVIDIA-LICENSE` | NVIDIA 610.43.03 firmware | upstream `assets/` |
| `upstream/` | NekoMirra source, pinned commit | `git -c core.autocrlf=false clone <repo> local/upstream` |
| `tools/zig-x86_64-windows-0.14.1/` | compiler | zig 0.14.1 zip in the manifest |
| `install-record.json`, `mok-enrolled.json` | the install's phase and what it changed; the key last seen enrolled | written by `kachow.ps1`; once installed, they live in the protected copy (see Install) |
| `build/`, `logs/`, `results/`, `backups/` | outputs; `backups/` holds the pre-install snapshots | |

```bash
openssl req -new -x509 -newkey rsa:2048 -keyout MOK.key -out MOK.pem -nodes -days 3650 -subj "/CN=Tensor Unlock MOK/O=Personal" -addext extendedKeyUsage=codeSigning
openssl x509 -in MOK.pem -outform DER -out MOK.cer
openssl pkcs12 -export -out MOK.pfx -inkey MOK.key -in MOK.pem -passout pass:
```

Check every pinned file with `python -I bin/kachow.py verify`. It does not cover zig: check
the zip's hash against `toolchain.zig.sha256` in the manifest before you extract it
(`(Get-FileHash zig-x86_64-windows-0.14.1.zip).Hash`).

## Build and test

```powershell
.\bin\test.ps1          # creates .venv on first use
.\bin\build.ps1         # → local\build\signed\{auto,manual,dryrun,reltest}-grubx64.efi (elevated: reads the MOK key)
```

The build fails if an image differs from the hardware-verified build pinned in the
manifest. After an intended source change, run with `-AcceptNewHashes`, test on hardware
(dryrun first), then re-pin.

## Install

```powershell
.\bin\kachow.ps1 install
```

It elevates itself and first refreshes a **protected copy** in
`C:\Program Files\RTX40 Ka-chow!` (the folder and the two scheduled tasks keep the
project's first name, so existing installs carry on): the scripts, the signed images, firmware, public
certificate, a copy of the Python on PATH (only if its `python.exe` and DLLs are signed by
the Python Software Foundation; no site-packages), and the install's record and logs. Only
Administrators and SYSTEM can change it. Every `kachow.ps1` command, and both scheduled
tasks, run from that copy, so no ordinary account can change what runs elevated or as
SYSTEM; `uninstall` deletes it, keeping its logs in `local\logs\runtime-*`. From there it
checks the machine, shows the plan and the BitLocker recovery key, and asks once. It then:

- saves the boot configuration to `local\backups\`;
- copies the boot chain to the ESP with the **dry-run** build;
- adds the boot entry **after** Windows Boot Manager and asks the firmware for one boot of
  it (BootNext);
- stages the key enrollment if this key has not been seen enrolled;
- suspends BitLocker for the next boots and adds a logon task (Fast Startup stays as it is);
- offers to shut down.

Power on and log in after each step; the logon task brings the window back and carries on:

1. **Key enrollment** (first install only). A blue MokManager screen appears: press a key
   within 10 s → **Enroll MOK** → **Continue** → **Yes** → password `tensor` → **Reboot**.
   It restarts into Windows.
2. **Trial boot.** The dry-run build runs its checks through shim, writes nothing to the
   GPU, and starts Windows. The log must show it passed.
3. **First unlock.** The automatic build goes on the ESP. It counts down 3 s and unlocks.
   The log must show `status=unlocked`.
4. **Done.** Only now does the boot entry go first in the boot order, so every power-on
   unlocks. The logon task stays, hidden, and at each logon puts the entry back first if
   Windows moved it, re-creates it if it vanished, and notes the last boot in
   `local\logs\guard.log`. The keeper task goes in too (see
   [Hybrid (Optimus) mode](#hybrid-optimus-mode)); the guard adds it back if it is missing
   and notes a boot where the RTX was off before the keeper started.

Each step gets up to three boots (a warm GPU, Esc at the countdown, an unfinished
enrollment) and says why. Anything else stops the install with the reason, and Windows Boot
Manager stays first.

```powershell
.\bin\kachow.ps1 status       # what is installed, what the last boot did
.\bin\kachow.ps1 recover      # Windows Boot Manager first again, tasks off; files stay
.\bin\kachow.ps1 uninstall    # remove everything (boot logs kept in local\logs)
```

An install made before `kachow.ps1` is adopted by `install` when its last boot unlocked.
`.\bin\deploy.ps1 -Variant manual|dryrun|reltest|auto` swaps the unlocker image on an
installed ESP. Variants: **auto** unlocks when the 3 s countdown ends (Esc opens the menu,
for stock Windows); **manual** ends the countdown in stock Windows, U unlocks; **dryrun**
and **reltest** never write to the GPU.

### The signing key

Shim boots anything signed with your MOK under Secure Boot, and the key stays enrolled
after `uninstall`. `MOK.key` and `MOK.pfx` have no passphrase; only their permissions
(Administrators and SYSTEM) protect them. Once the install has finished, move both off
the machine (`MOK.cer` and `MOK.pem` can stay): they are needed again only to build or
re-sign. To take the key out of the firmware, boot an Ubuntu live USB (it starts through
shim), run `sudo mokutil --delete MOK.cer`, set a one-time password, and confirm **Delete
MOK** in MokManager at the next boot.

## Benchmark

`bench.ps1` needs a Python with torch 2.7+ and CUDA, by default `local\.venv-bench`:

```powershell
python -m venv local\.venv-bench
local\.venv-bench\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128
```

## Start-screen banner

The unlocker prints `config/banner.txt` above its first line. Edit the file (UTF-8, at
most 20 lines of 79 columns, one console cell per character), then run
`.\bin\banner.ps1` as administrator: it copies the art to the ESP's `\GPU4090-ASSETS\`
with no rebuild or re-signing. If the firmware font cannot draw a character (braille,
for one, is not in every UEFI font), the unlocker shows the ASCII copy instead, which
`banner.ps1` prints so you can see it. Delete the file and run it again for no banner.

## Limits

- **Discrete or hybrid mode.** Discrete mode needs nothing more: the RTX drives the panel
  and stays powered, but the USB-C/HDMI outputs do not work in that mode. Hybrid mode
  relies on the keeper ([Hybrid (Optimus) mode](#hybrid-optimus-mode)); the driver's own
  `RMForceRtd3D3Hot=1` did not keep the unlock (0.62).
- Use Shut down, Restart or Hibernate, not Sleep (see
  [The unlock needs a power-on](#the-unlock-needs-a-power-on)).
- The boot entry is not in the BCD store: `bcdedit /copy` put a BCD blob
  in its optional data, which shim read as a file name ("Failed to open", "Failed to load
  image: Invalid Parameter"). `bcdedit /enum firmware` lists it as a "Firmware Application".
- Tested on one AN515-58 (BIOS V2.21, VBIOS 95.07.21.00.08); upstream on a MECHREVO GM5HG0A.
- The unlocked tensor cores draw more power. Watch temperatures.

## Recovery

Built in:

- **Until a boot has unlocked, Windows Boot Manager boots first.** The unlocker only runs
  on the one boot the firmware was asked for. If that boot hangs, hold power 10 s and power
  on: Windows starts as before.
- **At every countdown, Esc** starts Windows without the unlock.
- **A failed install step** puts Windows Boot Manager first, stops the logon task and says
  why.
- **`recover`** does the same by hand, at any time.
- **`uninstall`** works from any state, with or without an install record.
- **The boot logs** go to `local\logs\` after every step and before any uninstall, with a
  boot-configuration snapshot in `local\backups\`.

If Windows does not start at all: hold power 10 s, open the firmware setup at power-on (F2
on the AN515-58; other laptops use other keys), put **Windows Boot Manager** first (or pick
it from the boot menu, F12 on the AN515-58), then run `.\bin\kachow.ps1 recover` or
`uninstall`. Neither suspends BitLocker, so the next boot may ask for the recovery key:
enter the one that `install` showed. If the screen
says `STOPPED`, hold the power button.

## Licences

This project: GPL-2.0-only ([LICENSE](LICENSE)), the licence of the upstream unlocker its
patches modify. Shim: BSD-2-Clause (Canonical build, Microsoft-signed). NVIDIA firmware:
NVIDIA licence (`local/assets/NVIDIA-LICENSE`), not redistributed here.
