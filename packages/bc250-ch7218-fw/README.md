# bc250-ch7218-fw

Firmware images and a manual flash command for the **UGREEN DisplayPort to HDMI 2.1
adapter** (DP134 / 85564, DP135 / 85996), which is built on a Chrontel **CH7218A**.

Nothing in this package runs by itself. No service, no hook, no timer. You flash
the adapter by typing a command, and only an adapter on firmware `07.00.xx`
(`07.00.54` or an older build of that line) is accepted.

## Why

With stock firmware the adapter stops resending the HDMI scrambling setup a few
minutes after the picture starts. After that, anything that resets the TV or
receiver's HDMI state without dropping the link for long (an AV receiver input
switch, a TV standby and wake) leaves a black picture, while the DisplayPort side
still reports a healthy link. The source never learns, so nothing retrains. A
second watchdog, for the HDMI 2.1 link (FRL), has the same one-shot design.

The `tmds` image keeps the first watchdog running. On the author's board a
stock-firmware adapter went black after about six minutes; with `tmds` flashed it
survived a seven minute idle and a receiver input switch, and the author has not
had a no-signal since.

## The three images

| name | file | what it is |
| --- | --- | --- |
| `original` | `CH7218A-IMG.G000.07.00.54.IMG` | UGREEN's firmware, byte for byte as UGREEN published it |
| `tmds` | `...07.00.54.nowatchdog-tmds.IMG` | the original with the TMDS watchdog's countdown removed (one byte). **In use on the author's board.** |
| `tmds-frl` | `...07.00.54.nowatchdog-tmds+frl.IMG` | `tmds` plus the same change to the FRL monitor (a second byte). **Not tested on hardware yet.** |

Exactly what differs from `original` (file offsets; the image is
`[length u16 LE][code][16-bit sum of the code, LE]`):

| offset | original | `tmds` | `tmds-frl` | meaning |
| --- | --- | --- | --- | --- |
| `0x1A4E` | `0x14` | `0x00` | `0x00` | `DEC A` becomes `NOP` in the TMDS watchdog |
| `0x27C0` | `0x14` | `0x14` | `0x00` | `DEC A` becomes `NOP` in the FRL monitor |
| `0x6DF2` | `EA` | `D6` | `C2` | low byte of the stored checksum |

Nothing else differs. The repository's tests rebuild both images from `original`
and compare them byte for byte.

The `tmds-frl` image is untested. The author left the FRL monitor alone at first
because a watchdog that never gives up could, in principle, keep retraining a link
to a sink that has gone to sleep. Treat it as an experiment, and go back to
`tmds` or `original` if the picture misbehaves.

## Where the files come from

- `ch7218_fwu` is UGREEN's own Linux updater for this adapter, unmodified
  (sha256 `79a87d9d0f4def58a3792661c1055de26d8f9cf29f0537ab316d31826bc42788`).
- `original` is the image from UGREEN's firmware-update instructions, unmodified.
- UGREEN distributes this firmware and updater to the end users of the adapter.
  This package mirrors them, plus the two fixed images, so people with the same
  adapter can install them from one place. It is not endorsed by UGREEN or
  Chrontel. If either company asks for a file to be removed, it will be.

## Using it

```
bc250-ch7218-flash list                         # the three images and their checksums
sudo bc250-ch7218-flash status                  # find the adapter, read its firmware version
sudo bc250-ch7218-flash flash tmds              # flash one of: original | tmds | tmds-frl
sudo bc250-ch7218-flash flash tmds --dry-run    # do every check, write nothing
```

Options for `flash`: `--aux N` picks the adapter when more than one is found
(use the number `status` shows), and `--yes` skips the "type flash" question.

Run it **from SSH, not from the screen the adapter drives**: the picture goes
away while it writes. The write takes a few seconds. Do not cut power until it
prints `Update Success`.

The new code only runs after the adapter is power-cycled: unplug its DisplayPort
end for five seconds, or power the whole board off and on.

### What it checks before writing anything

1. The image is exactly the one the package shipped (SHA-256) and passes the
   updater's own length and checksum rule.
2. Exactly one adapter is found, by the Chrontel identity it reports over
   DisplayPort (`2B 02 F0` and the name `CH7218`), or you named it with `--aux`.
3. The adapter reports firmware `07.00.xx` with `xx` no higher than 54. An older
   build on that line is updated (flashing any of the three images also brings it
   up to 07.00.54, which is what UGREEN's own update does). A newer build (that
   would be a downgrade), another line such as `07.08.xx`, a USB-C variant, or
   another vendor's cable that uses this chip is refused, because these images
   are built from the 07.00.54 code. The firmware version is read from the chip
   with UGREEN's updater (`-v`).
4. You type `flash`, unless you passed `--yes`.

UGREEN's updater always opens `/dev/drm_dp_aux1`. The wrapper therefore runs it in
a private mount namespace in which `/dev/drm_dp_aux1` is the adapter you chose and
no other DisplayPort AUX node exists, so it cannot reach a different one. Nothing
outside that namespace changes.

### Going back, and when something goes wrong

Flash `original` at any time to return to UGREEN's firmware. The updater reads the
flash back and compares it, so `Update Success` means the data matched. The three
images report the same version number, so `status` cannot tell them apart; it
shows the last image this tool flashed.

If a write is interrupted or reports an error, do not power the adapter off.
Run the same command again. Interrupting a flash can in principle leave the
adapter unable to start, which is why the checks above are strict. Flashing is at
your own risk.

## What it does not do

It does not touch any adapter that is not a CH7218 at `07.00.54`, it does not run
at boot or on upgrade, and it is not part of `linux-cachyos-bc250-meta`.
