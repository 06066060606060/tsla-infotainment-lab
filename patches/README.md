# QEMU storage experiment

`qemu-10.0.11-sd-erase-batching.patch` targets QEMU tag `v10.0.11`, commit `e3ad0582fdcec5c194835b0b4e8342cdc197b5cb`.

The upstream SD erase path writes 0xff one 512-byte sector at a time. Large first-boot filesystem discards therefore take many minutes. The patch batches contiguous SDHC erases into at most 1 MiB writes. It retains 0xff, the inclusive final sector, boot-partition addressing, and the existing SDSC write-protect handling. Failed batch writes fall back to the original sector path. It does not replace erasure with zeroes or skip guest initialization.

Guest-level validation on September 16, 2026 used a separate 4 GiB scratch SDHC disk and a Debian maintenance kernel. Erasing 64 MiB plus one sector took approximately 9.63 seconds with the installed QEMU and 0.02 seconds with this build, measured inside the guest. Host readback confirmed every erased byte was 0xff and both adjacent sectors were unchanged. These are local measurements, not a general performance guarantee.

The patched build subsequently booted the original MCU2 kernel into firmware service startup. It remains an experimental build and is not selected by the application by default. No QEMU executable is included here. The modified `hw/sd/sd.c` retains its upstream BSD license; redistribution of a complete QEMU build must also comply with QEMU's overall licenses and corresponding-source requirements. The upstream source remains in the separate local build directory.

Source: https://github.com/qemu/qemu/blob/v10.0.11/hw/sd/sd.c

## Reproduce the readback check

On Linux, use the extracted Debian maintenance kernel directory described in
`docs/qemu.md`. The helper builds its own initramfs from the local maintenance
tools and creates a temporary 4 GiB sparse disk; it needs no firmware:

```sh
python3 scripts/benchmark_sd_erase.py \
  --kernel-root "$HOME/.local/share/tsla-infotainment-lab/qemu-tools/debian-kernel" \
  --qemu /path/to/qemu-system-x86_64
```

The JSON result separates total host runtime from guest erase time. Guest
uptime has 0.01-second resolution, so a reported 0.0 is below that resolution.
Use `--length` to change the number of erased bytes. Additional real-guest
readback checks passed at 512, 1048064, 1048576 and 1049088 bytes, covering both
sides of the 1 MiB batching boundary. Temporary files are removed after QEMU
exits; no host block device is opened.
