# Protonfixes regression inputs

`ge-proton11-6-upscalers.py` is the complete unmodified upscaler module from
[GE-Proton11-6](https://github.com/GloriousEggroll/proton-ge-custom/releases/tag/GE-Proton11-6).
Its SHA256 is `4128896c4134d865a290e2e8e62279d07157131b207f4bc7d29e8c873fe85645`.

`cachyos-native-upscalers.py` is the complete unmodified `upscalers.py` of
CachyOS's protonfixes submodule at `8dadc914d8f1` (umu-protonfixes by
loathingKernel, commit 65433bb, 2026-10-17), the file `proton-cachyos-native`
and the Steam Linux Runtime package build. Its SHA256 is
`c73c4827035f3db58088f66fb17b89f7b775616da8fb643d3b06474daa7ca911`.
CachyOS no longer carries its own `patches/protonfixes` upscaler set, so this
is the file the repository's pinned-manifest patch applies to. Replace it, and
its hash in `tests/test_fsr4_runtime.py`, when the submodule moves and the patch
stops applying (the build log names the failed hunks).
Tests verify both base hashes before applying the package patches.

Only the logger and cache-directory imports are stubbed. The modules' actual
manifest validation, filesystem writes and archive handling run unchanged in
temporary prefixes with network access forbidden.

The original module comes from
[umu-protonfixes](https://github.com/Open-Wine-Components/umu-protonfixes/blob/d13333be729b3018f9f9bc6790944901319b425b/LICENSE).
Its license follows.

```text
BSD 2-Clause License

Copyright (c) 2018, Chris Simons

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
