# BC-250 CachyOS kernel repository

GitHub Actions builds the official CachyOS kernel with the BC-250 patches for
**x86-64-v3**, publishes the Arch packages as GitHub release assets, and turns
each fixed channel release into a pacman repository.

## Included patches

- BC-250 hybrid 6/8-core SMU telemetry layout
- GPU activity reporting
- Safe GFX clock fallback: the 8-core layout never interprets `C0Residency[6]`
  as `GfxclkFrequency`
- Cyan Skillfish DisplayPort audio quirk through `ignore_dpref_ss`

## Build channels

| Input | Upstream PKGBUILD | Package base | Release tag | Repository name |
|---|---|---|---|---|
| `stable` | `linux-cachyos` | `linux-cachyos-bc250` | `repo-stable` | `bc250-cachyos-v3` |
| `rc` | `linux-cachyos-rc` | `linux-cachyos-rc-bc250` | `repo-rc` | `bc250-cachyos-v3-rc` |

Scheduled and push builds use the repository variable `SCHEDULE_VARIANT`. When
the variable is unset, the workflow defaults to `rc`; set it to `stable` after
Linux 7.2 reaches the normal `linux-cachyos` package, or to `both` to maintain
both channels. The workflow calculates a fingerprint from the upstream
PKGBUILD/config and local patches and skips an unchanged channel. A manual run
can always select `stable`, `rc`, or `both`.

## CPU target

The build exports:

```bash
_processor_opt=generic_v3
```

The CachyOS PKGBUILD converts that to `CONFIG_GENERIC_CPU=y` and
`X86_64_VERSION=3`. It does **not** use the GitHub runner's native CPU.

The build container intentionally does not expose `CI` or `GITHUB_RUN_ID` to
`makepkg`, because the CachyOS PKGBUILD otherwise selects its reduced CI config
instead of the normal performance config.

Check client compatibility before installing:

```bash
/lib/ld-linux-x86-64.so.2 --help | grep 'x86-64-v3'
```

## Enable the repository

The GitHub repository must be public for anonymous pacman downloads. Replace
`OWNER/REPOSITORY` below with the actual GitHub path.

### Stable

Add to `/etc/pacman.conf`:

```ini
[bc250-cachyos-v3]
SigLevel = Optional TrustAll
Server = https://github.com/OWNER/REPOSITORY/releases/download/repo-stable
```

Then install:

```bash
sudo pacman -Syu linux-cachyos-bc250 linux-cachyos-bc250-headers
```

### Release candidate

```ini
[bc250-cachyos-v3-rc]
SigLevel = Optional TrustAll
Server = https://github.com/OWNER/REPOSITORY/releases/download/repo-rc
```

```bash
sudo pacman -Syu linux-cachyos-rc-bc250 linux-cachyos-rc-bc250-headers
```

The channel releases are recreated at the same fixed tags, so the pacman URL
never contains the kernel version. The repository database and packages are
uploaded together to the same release.

## Publishing model

Each successful channel build produces:

- kernel and headers `.pkg.tar.zst` packages
- `<repo>.db` and `<repo>.files` for pacman
- compressed repository databases
- `PKGBUILD`, `config`, `.SRCINFO`
- `SHA256SUMS` and `build-info.env`

`github.run_number` is appended as a numeric pkgrel subrelease. This guarantees
that a forced rebuild or patch revision has a newer package version even when
the upstream kernel version did not change.

## Signing

The generated repository is currently unsigned, hence the example uses:

```ini
SigLevel = Optional TrustAll
```

GitHub HTTPS and the published SHA-256 file provide transport and manual
integrity checks, but this is not equivalent to pacman package signing. A future
revision can import a private OpenPGP key from GitHub Actions secrets and sign
both packages and repository databases.

## Local build

On an Arch/CachyOS system with the normal build dependencies available:

```bash
CACHYOS_VARIANT=linux-cachyos-rc \
BC250_PKGREL=1 \
./scripts/build-package.sh
```

The output repository is written to `out/rc/` or `out/stable/`.

## Important behaviour

Patch application is deliberately strict. When a future CachyOS source change
makes a hunk incompatible, `makepkg` stops during `prepare()` instead of
silently publishing an unverified kernel.
