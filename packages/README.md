# packages/

Pre-built Debian packages for `ka9q-radio`, built from source using its own
real Debian packaging (`debian/` in the upstream tree — `dh`/debhelper,
compat 13, not hand-rolled). This directory holds the build *output*, not
a source checkout — see [Provenance](#provenance) for exactly what was
built and how, so this can be reproduced or re-verified later rather than
trusted blindly.

## What's here

19 binary `.deb` packages plus the `.changes`/`.buildinfo` files for
provenance. Debug-symbol `.ddeb` packages (only useful for `gdb` crash
debugging, ~1.4MB combined) were **not** included here — rebuild from the
same commit (below) if you need them.

| Package | What it is |
|---|---|
| `ka9q-radio` | The `radiod` daemon itself + its systemd template unit |
| `ka9q-radio-common` | Shared files, presets, the `radio` system user setup |
| `ka9q-radio-rx888`, `-hackrf`, `-rtlsdr`, `-airspy`, `-airspyhf`, `-bladerf`, `-funcube` | Per-device front-end driver plugins (`.so`) |
| `ka9q-radio-control`, `-monitor`, `-tools` | Operator CLI utilities (`control`, `monitor`, `pcmrecord`, `metadump`, etc.) |
| `ka9q-radio-ft`, `-packet`, `-hfdl`, `-horus`, `-recordings` | Optional decode/logging subsystems |
| `ka9q-radio-siggen` | Software signal generator plugin |
| `ka9q-radio-full` | Meta-package depending on the above (see caveat below) |

**Not built: `ka9q-radio-fobos`, `ka9q-radio-hydrasdr`.** Both need
third-party vendor headers (`libfobos-dev`, `libhydrasdr-dev`) that are
not apt-installable and not present on this host, and neither device is
present on this build — same reasoning as `scripts/phase6-ka9q-radio.sh`'s
own `ENABLE_FOBOS=0 ENABLE_HYDRASDR=0` (see that script's comments and
`docs/mcp-validation-evidence.md`'s 2026-08-11 entries for the full
build-failure history this avoids). **`ka9q-radio-full`'s `Depends:` was
edited to drop those two packages** so installing it doesn't fail looking
for packages that don't exist in this set — everything else in
`debian/control` is unmodified upstream packaging. `ka9q-radio-repeater`
isn't here either — it's Raspberry Pi/arm64-only per its own description,
this is an `amd64` build.

## Provenance

- Source: `https://github.com/ka9q/ka9q-radio.git`
- Commit: `1c0a4231d20f4257569715325242d6f2432dd939` (`main`, 2026-08-10 —
  same commit `scripts/phase6-ka9q-radio.sh` builds from source; see that
  script for how/why this commit was chosen over bare `main`)
- Built: 2026-08-11, on this project's own host (Ubuntu 24.04, amd64),
  via `dpkg-buildpackage -us -uc -d -j$(nproc)` with
  `ENABLE_FOBOS=0 ENABLE_HYDRASDR=0` exported (same flags as the
  from-source install path, for the same reason)
- Version string: `2026.08.10-1-trixie1` (from upstream's own
  `debian/changelog` — the `-trixie1` suffix is upstream's own naming, not
  a claim this was built on/for Debian Trixie; this build was verified on
  Ubuntu 24.04 only)
- `-d` (`--no-check-builddeps`) was used specifically to bypass the
  `libfobos-dev`/`libhydrasdr-dev` Build-Depends that can't be satisfied
  on this host — every *other* Build-Depends was confirmed actually
  installed before building, not skipped wholesale

## Installing

These are ordinary local `.deb` files — no repository/PPA involved:

```bash
sudo apt install ./packages/ka9q-radio-common_2026.08.10-1-trixie1_amd64.deb \
                  ./packages/ka9q-radio_2026.08.10-1-trixie1_amd64.deb \
                  ./packages/ka9q-radio-rx888_2026.08.10-1-trixie1_amd64.deb \
                  ./packages/ka9q-radio-hackrf_2026.08.10-1-trixie1_amd64.deb \
                  ./packages/ka9q-radio-rtlsdr_2026.08.10-1-trixie1_amd64.deb \
                  ./packages/ka9q-radio-control_2026.08.10-1-trixie1_amd64.deb \
                  ./packages/ka9q-radio-monitor_2026.08.10-1-trixie1_amd64.deb \
                  ./packages/ka9q-radio-tools_2026.08.10-1-trixie1_amd64.deb
```

(`apt install ./file.deb`, not `dpkg -i`, so apt also pulls in the runtime
library dependencies each package declares — `dpkg -i` alone will leave
those unresolved.) Pick only the front-end driver packages you actually
need; `ka9q-radio-common` and `ka9q-radio` itself are required regardless.

**This has NOT been used to (re)install the actual running system.**
`scripts/phase6-ka9q-radio.sh`'s from-source `make install` path is what
this host's live `radiod@rx888-hf`/`radiod@hackrf-2m` are actually running
as of 2026-08-11 (verified — see `docs/mcp-validation-evidence.md`). These
`.deb`s are built from the identical commit and build flags, but installing
them over that from-source install is untested — back up
`/etc/radio/`, expect `dpkg`/`make install`'s file layouts to mostly but
not necessarily perfectly overlap, and don't do it on this host's live
production instances without a deliberate test first.

## Rebuilding / updating

The pin (`1c0a4231d2...`) will go stale the same way
`scripts/phase6-ka9q-radio.sh`'s did (see that script's own history) —
there's no mechanism here that automatically tracks new commits. To
rebuild against a newer commit:

```bash
git clone https://github.com/ka9q/ka9q-radio.git /tmp/ka9q-pkg-build
cd /tmp/ka9q-pkg-build
git checkout <new-commit>
sudo apt-get build-dep -y --arch-only . 2>&1 | true   # will warn about fobos/hydrasdr, expected
python3 - <<'PY'
import re
content = open("debian/control").read()
stanzas = content.split("\n\n")
kept = [s for s in stanzas if not re.match(r"^Package: ka9q-radio-(fobos|hydrasdr)\b", s)]
def strip(s):
    for n in ("ka9q-radio-fobos", "ka9q-radio-hydrasdr"):
        s = s.replace(n+", ", "").replace(", "+n, "").replace(n, "")
    return s
open("debian/control", "w").write("\n\n".join(strip(s) for s in kept) + "\n")
PY
cat >> debian/not-installed <<'EOF'
usr/lib/udev/rules.d/51-hydrasdr.rules
usr/share/ka9q-radio/defaults/16d0-132e-a1d610000207.conf
usr/share/ka9q-radio/defaults/16d0-132e.conf
usr/share/ka9q-radio/defaults/1d50-60a1-hydrasdr_sn:36b463dc31514fc7.conf
usr/share/ka9q-radio/defaults/38af-0001-hydrasdr_sn:36b463dc31514fc7.conf
usr/share/ka9q-radio/defaults/38af-0001.conf
usr/share/ka9q-radio/defaults/fobos.conf
usr/share/ka9q-radio/defaults/hydrasdr.conf
usr/share/ka9q-radio/examples/radiod@aviation.conf
usr/share/ka9q-radio/examples/radiod@fobos-generic.conf
usr/share/ka9q-radio/examples/radiod@ka9q-fobos.conf.d/00-global.conf
usr/share/ka9q-radio/examples/radiod@ka9q-fobos.conf.d/02-fobos.conf
usr/share/ka9q-radio/examples/radiod@ka9q-fobos.conf.d/03-aviation.conf
usr/share/ka9q-radio/examples/radiod@ka9q-fobos.conf.d/04-aviation-raster.conf
usr/share/ka9q-radio/examples/radiod@ka9q-fobos.conf.d/05-acars.conf
EOF
ENABLE_FOBOS=0 ENABLE_HYDRASDR=0 dpkg-buildpackage -us -uc -d -j"$(nproc)"
```

The `debian/not-installed` list above is exactly what was needed for
commit `1c0a4231d2...` — a newer commit may add/rename/remove fobos or
hydrasdr default-config files, in which case `dh_missing` will name
whatever's actually unclaimed; adjust the list to match its real output
rather than assuming this exact list still applies.
