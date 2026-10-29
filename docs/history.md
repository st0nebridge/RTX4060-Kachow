# How the boot chain was made to work (2026-10-28)

Each failure, what it looked like, and the fix. Boot logs RUN0001–RUN0018 are the
evidence; the full RUN0018 is `tests/fixtures/RUN0018-auto-unlocked.txt`.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Reading firmware variables from Windows fails with error 1314 | SeSystemEnvironmentPrivilege is disabled by default, even for administrators | enable it with AdjustTokenPrivileges (`FirmwareVars.psm1`) |
| 2 | No MokManager, brief "Security Violation", Windows boots | shim opens MokManager's enroll menu only when a request is pending | stage MokNew + MokAuth from Windows (`stage-mok.ps1`, `kachow.mok`) |
| 3 | Key enrolled, grubx64.efi still refused | shim 15.4+ requires an `.sbat` section in every second stage | `kachow.sbat` before signing |
| 4 | Unlocker skips with "secure-boot" (0x…1a) | upstream refuses Secure Boot (it ships unsigned) | patch: accept it when shim's SHIM_LOCK protocol is present |
| 5 | Skips at "display-preflight" (0x…06) in hybrid mode | the firmware console splitter's GOP has no device path | patch: `Mirror()` accepts it when it mirrors a pathed GOP |
| 6 | "Security Violation (0x1A)" at boot | an **unsigned** grubx64.efi was deployed: `re-sign.ps1` piped into `Select-Object -First 1`, which stops the script in Windows PowerShell 5.1 before it signs | no pipe; signing verifies its own output; every deploy asserts the MOK signature (`Signing.psm1`) |
| 7 | Hybrid mode: TRANSACTION OK, but Windows benchmark still half rate | Windows powers the idle RTX off (D3) within ~2 min of boot, resetting it | discrete-GPU mode; `RMForceRtd3D3Hot=1` tried (0.62), removed; since 2026-10-29 the keeper task (README: Hybrid mode) |
| 8 | Discrete mode: no U prompt | the console GOP now mirrors the RTX's own screen | `Mirror()` accepts any pathed GOP |
| 9 | Discrete mode: STOPPED at display release (safe: driver reconnected, no GPU write) | after the RTX display driver stops, the console splitter keeps the released screen's mode | patch: `StaleOwnScreen()` matches it to a preflight-owned framebuffer |
| 10 | — | manual build verified (42.2 TFLOPS), then the automatic build | RUN0018 `TRANSACTION OK`, 45.5 TFLOPS, ratio 1.00 |

Notes that still matter:

- `Set-AuthenticodeSignature` on a self-signed MOK reports `UnknownError` in Windows;
  shim checks the signer against MokList, so only the thumbprint matters.
- BitLocker seals to PCR 7+11; suspend it for the boots that change the chain
  (`install.ps1`, `deploy.ps1` do).
