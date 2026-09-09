# Protonfixes regression inputs

`ge-proton11-6-upscalers.py` is the complete unmodified upscaler module from
[GE-Proton11-6](https://github.com/GloriousEggroll/proton-ge-custom/releases/tag/GE-Proton11-6).
Its SHA256 is `4128896c4134d865a290e2e8e62279d07157131b207f4bc7d29e8c873fe85645`.

Applying `ge-to-cachyos-native.patch` reconstructs the complete native base
with SHA256 `3380cea841b3a52de9fdfe151631e1c24b7ec9707d7d77fb0eea68d42aa6140c`.
It was obtained by reversing this repository's pinned-manifest patch from the
published `proton-cachyos-native-bc250-11.0.20260703-3.111` module (package SHA256
`23340f90099bec606c5faf6e1f077aba426802de5a466c69a15a311c13f62f4e`).
The native package uses
[CachyOS's 11.0-20260703-native source](https://github.com/CachyOS/proton-cachyos/tree/cachyos-11.0-20260703-native).
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
