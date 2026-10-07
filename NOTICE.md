# Notice

This repository is an independent build workspace derived from public upstream work.

Upstream sources:
- Numbersf/Action-Build
- Numbersf/AnyKernel3
- SukiSU-Ultra/SukiSU-Ultra
- simonpunk/susfs4ksu
- sidex15/susfs4ksu-module

Local changes:
- Device-specific OnePlus build entries from the upstream manifest workflow.
- SukiSU Ultra kernel version fixed to 40959.
- KPM and SUSFS required.
- SUSFS 2.3.0 checked at build time.
- Unicode/zero-width fix required.
- HMBIRD/Fengchi is preserved when already present, patched only when a matching device patch exists, otherwise skipped.
- ZRAM/LZ4 update, Re-Kernel, DroidSpaces, SUSFS development branch and CCM are disabled in automated batches.
- AnyKernel3 installer shows xiaomo branding and installs the bundled SUSFS module automatically after a successful kernel write when an existing ksud is available.
- CI build success is not a substitute for real-device boot testing.
