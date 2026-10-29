# Security review, 2026-10-29

Question: does anything this project installs from NekoMirra/rtx4060-laptop-tensor-unlock
(pinned commit `7c6a43e`), or the third-party binaries next to it, carry malware?

**Answer: no malicious behaviour or tampered binary was found.** Every binary matches its
official publisher byte for byte, and the unlocker's code touches nothing but the RTX, its
own log folder, and an unmodified, Secure-Boot-verified Windows Boot Manager. Two
weaknesses in this project's own setup were found (H-1, M-1 below); both are fixed.

## What runs, and where it comes from

| Component | Runs on | Provenance check | Result |
|---|---|---|---|
| Unlocker (`grubx64.efi`) | CPU, pre-boot | built here from the pinned source + `patches/`; the unpatched source also rebuilds upstream's four `prebuilt/*.EFI` byte for byte | source reviewed, see below |
| `shimx64.efi`, `mmx64.efi` | CPU, pre-boot | extracted from `shim-signed_1.59+15.8-0ubuntu2_amd64.deb`, whose SHA-256 (`f8ed71ce…`) is in Ubuntu's Packages index; shim is signed by Microsoft UEFI CA 2011 and Canonical | identical |
| zig 0.14.1 | build only | `ziglang.org/download/index.json` | identical |
| `booter_load_ad102.bin`, `gsp_boot_ad102.bin`, `gsp_boot_desc_ad102.bin` | GPU | decoded independently from NVIDIA's open kernel module 610.43.03 bindata (archive hash matches NVIDIA's `.sha256sum`) | identical (booter adds only an 80-byte header) |
| `gsp_ga10x.bin` (84 MB, runs on the GSP with DMA) | GPU | extracted from NVIDIA's official `NVIDIA-Linux-x86_64-610.43.03.run` (`45e2d4c1…`, matches NVIDIA's published hash) | identical (`57237362…`) |
| `v67-ad102-610.43.03-four-plm.bin` | GPU (data) | not an NVIDIA file: 16,000 copies of `0x0000019C` plus 25 words, which equal `generate_v67.py`'s `AD102_PATCHED_WORDS` exactly | a table of four GPU register targets (`0x009A0148`, `0x001FA7C4`, `0x001FA7CC`, `0x00823804`), their values and a marker; no code |

Microsoft Defender (signatures 1.463.16.0) found nothing in `local\upstream`, `local\efi`,
`local\assets`, `local\build` or the old kit's `downloads` (about 15,500 files). Every
`.efi` on the ESP is Microsoft-signed or matches `third_party/manifest.json`; no WPBT table,
no services, Run keys or tasks other than this project's.

Upstream code that ever ran here: only `prebuilt/DRYRUN4090.EFI`, once (RUN0001, 28 Oct,
stopped at its Secure Boot check before touching the GPU); it is byte-identical to a build
of the reviewed source. Upstream's `package/*.ps1`, `*.cmd`, `mma_bench.exe` and Python
scripts were never run.

## Unlocker source review (15 compiled files, about 4,500 lines)

- **No bootkit primitives.** No `SetVariable` (boot variables, Secure Boot keys and other
  firmware variables are only read), no `ExitBootServices`/`SetVirtualAddressMap` hooks, no
  capsule or flash update, no ACPI or configuration-table install, no protocol install, no
  network, no block or disk I/O, no inline assembly beyond a `pause`, no port I/O or MSRs.
- **Windows hand-off** (`boot_io.c:225-282`): `bootmgfw.efi` is read, hashed for the log and
  passed unmodified to the firmware's `LoadImage`, which checks Microsoft's signature.
- **Files:** writes only `\GPU4090-UNLOCK\RUNnnnn.TXT` (a 40-slot ring) on its own volume.
- **Hardware:** every register write goes through the RTX's own `EFI_PCI_IO_PROTOCOL`,
  bounded to BAR0 (`port.c:131`, `compat.c:11-19`); config writes stay in its own 256-byte
  space (`port.c:157`); the selector `SS1` can be written once, with 8, at one step. The
  device is admitted only if it is the single `10de:28a0` in the system (`app.c:39-89`).
- **DMA:** the GPU gets only buffers allocated for it (`port.c:76-104`); bus mastering is
  disabled and verified before Windows (`release.c:373-385`), after a Function Level Reset.
- `patches/secureboot-shim.patch` and `patches/start-banner.patch` add no such calls.

By design the transaction loosens GPU-internal locks (FEAT, FBPA, WPR PLMs). The reset puts
WPR back (RUN0021: `0x4cb8f`); FEAT stays open for the session, which is the unlock itself
and lets only code that already has GPU register access (a kernel driver) change the rate.

## Findings

**H-1 (High): the MOK private key can sign boot images for anyone on this PC.**
`local\keys\MOK.key` is an unencrypted PEM readable by `BUILTIN\Users` (and modifiable by
a local sandbox group); `MOK.pfx` has no password. Shim boots anything signed with this key
under Secure Boot, and the key stays enrolled after `uninstall`. Precondition: code running
as any local account. Impact: a bootkit that survives reinstalling Windows. Mitigation:
keep the key off the machine or passphrase-protected, used only to re-sign; if it may have
leaked, delete the MOK in MokManager and enroll a new one.
*Fixed 2026-10-29:* `MOK.key` and `MOK.pfx` are owned by Administrators
with inheritance off and only Administrators and SYSTEM allowed; verified that the user's
unelevated token can no longer read either, while signing works elevated. Verification now
reads only the public `MOK.cer`. The key was readable by every local account from
2026-10-28 07:36 to 2026-10-29 06:27; rotate it if untrusted code ran under another local
account in that window. The owner kept the key (not rotated).

**M-1 (Medium): the SYSTEM keeper task and the elevated logon task run user-writable code.**
`bin\keeper.ps1`, `src\windows\*.psm1`, `bin\kachow.py` and `src\kachow\` inherit Modify
for `Authenticated Users` and a local sandbox group from the checkout folder; the keeper's
`python.exe` (`%LOCALAPPDATA%\Programs\Python\Python311`) is writable by the user's
unelevated token. Editing either runs that code as SYSTEM at the next startup (and the
logon task's script elevated at logon). Precondition: code running as a local account or
sandbox user. Mitigation: run the tasks from a copy under an admin-only directory (for
example `%ProgramFiles%\RTX40 Ka-chow!`) and drop the user-writable Python from the SYSTEM
path, e.g. a PowerShell keeper calling `nvcuda.dll` directly.
*Fixed 2026-10-29:* both tasks and every `kachow.ps1` command run from
`C:\Program Files\RTX40 Ka-chow!` (owner Administrators, inheritance off, Users read and
run), with its own copy of a PSF-signed Python and its own state; the tasks refuse to
register from anywhere else. Verified unelevated: writing the keeper script, a log or the
copy's `python.exe` is denied.

**L-1 (Low):** Ubuntu's Packages index was fetched over HTTP and its Release GPG signature
not checked; shim's Microsoft signature, which the firmware enforces, covers the gap.

## Public-release review (2026-10-29)

A second pass over the tree as published, for leaks and for risks to someone following the
README. No credentials, personal data or machine identifiers beyond the AN515-58's model
data were found. Risks, with what was done:

- **Fixed: the elevated logon task could load a user-planted module.** Windows PowerShell
  autoloads modules from the user's `Documents\WindowsPowerShell\Modules` first, so a
  module there named like `Storage` or `ScheduledTasks` would have run elevated at logon.
  `kachow.ps1` now limits `PSModulePath` to the two admin-only module folders before it
  calls any cmdlet.
- **Documented: the MOK key at rest.** It has no passphrase and stays enrolled after
  `uninstall`; the README (The signing key) says to move it off the machine after
  installing and how to delete the MOK.
- **Documented: zig is not covered by `verify`.** Only the zip's hash is pinned; the README
  says to check it before extracting.
- **Documented: `recover` and `uninstall` do not suspend BitLocker**, so the next boot may
  ask for the recovery key; the firmware keys in Recovery are the AN515-58's.
- **Documented: where to clone.** A checkout at the top of a drive inherits Modify for
  Authenticated Users; the README says to clone inside the user profile.
- **Open (Low): the protected Python copy is only partly verified.** `python.exe` and its
  DLLs must be signed by the Python Software Foundation, but `Lib\` and `DLLs\*.pyd` are
  copied unchecked. It matters only when the source Python sits in a folder other accounts
  can write.
- **Open (Low):** `Add-Type` in `FirmwareVars.psm1` compiles in the elevated user's
  `%TEMP%`.

## Method

Pinned checkout verified clean at `7c6a43e`; risky-API sweep plus a full read of `app.c`,
`boot_io.c` and the MMIO, config and DMA layers of `port.c`, `compat.c`, `release.c`;
`unlock_610.c`'s use of each asset; independent decoding or extraction of every binary from
its official source; rebuild of upstream's prebuilts; Defender custom scans; ESP, task,
service, Run-key and boot-entry inventory; ACL checks with `icacls`.
