# BC-250 AI benchmarks

The measurements behind the setups in [AI.md](AI.md): one board, 2026-11-14,
CachyOS with a kernel from this repository, all 40 CUs unlocked
(`amdgpu.bc250_cc_write_mode=3`), `amdgpu.sched_policy=2`, the default 512 MB
VRAM carve-out, game session stopped.

## The GPU clock matters most

`amdgpu` alone runs the BC-250's GPU at a low clock. The
[cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor)
raises it with load, but it measures load the way games produce it: ROCm compute
(PyTorch, ComfyUI) does not register, and the GPU then stays at the governor's
minimum. `systemctl isolate multi-user.target` also stops the governor.

| Workload | Clock | Result |
|---|---|---:|
| Qwen3.8-27B IQ3_XXS, llama.cpp Vulkan (package), generation | 1200 MHz (governor stopped) | 15.6 t/s |
| same | governor running (holds 2100 MHz) | **23.9 t/s** |
| same, prompt (512 tokens) | 1200 MHz | 117.5 t/s |
| same, prompt (512 tokens) | governor running | **191.0 t/s** |
| SDXL-Lightning 8 steps, 1024×1024, ComfyUI | 1200 MHz | 28.7 s per image |
| same | governor running (stays at 1000 MHz: compute is invisible to it) | slower still |
| same | fixed 2100 MHz through the governor's D-Bus `SetFixedFrequency` | **20.3 s per image** |

Most tables below were measured at 1200 MHz, before this was found. They
compare setups at the same clock, so which setup wins still holds; the absolute
numbers are lower than with the governor.

## LLM: Qwen3.8-27B

Qwen3.8-27B, Unsloth `UD-IQ3_XXS` (10.9 GB, 3.06 bits per weight), all layers on
the GPU, `llama-bench`, GPU at 1200 MHz:

| Backend | Build | Prompt, 512 tokens | Prompt, 64 tokens | Generation |
|---|---|---:|---:|---:|
| **Vulkan (RADV)** | CachyOS `llama-cpp` + `ggml-vulkan` (cd959bae99) | **117.5 t/s** | 100.8 t/s | **15.6 t/s** |
| Vulkan (RADV) | same commit, own release build (no asserts) | 118.0 t/s | | 15.7 t/s |
| Vulkan (RADV) | llama.cpp master 32bdc3a89 (2026-11-14), release build | 123.2 t/s | | 15.6 t/s |
| HIP (ROCm from `bc250-pytorch`) | cd959bae99, `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1013` | did not finish in 10 min | 44.0 t/s | 9.3 t/s |

"Prompt" is how fast it reads your input; "generation" is how fast it writes the
answer (15 tokens a second is roughly 11–12 words, faster than most people read).

**Use Vulkan, and the CachyOS packages are fine.** HIP works on the BC-250 with
this repository's ROCm, but it generates 1.7x slower and reads prompts 2.3x
slower, and long prompts crawl. The most likely reason: llama.cpp's HIP kernels
for quantised models lean on integer dot-product instructions (`v_dot4_i32_i8`)
that gfx1013 does not have (Vulkan reports `int dot: 0` for it as well), so they
fall back to slower code; the Vulkan shaders are written to do without. Vulkan
also needs no `sched_policy=2` and no ROCm at all. A build of current llama.cpp
master reads prompts 4% faster; generation is the same.

What else we tried (Vulkan, master):

| Setting | Result |
|---|---|
| Flash attention (`-fa 1`) | no difference; keep it on, the q8_0 KV cache needs it |
| Micro-batch `-ub` 256 / 512 / 1024 | 119.6 / 123.2 / 123.2 t/s prompt: the default 512 is best |
| 8k tokens already in context | prompt 110 t/s, generation 15.1 t/s |
| KV cache q8_0 instead of f16 (8k context) | generation 14.9 instead of 15.1 t/s, half the KV memory |

### How much context fits

Server mode, q8_0 KV cache, `--parallel 1`, `ttm.pages_limit=3670016` (GTT 14 GiB),
512 MB VRAM carve-out (BIOS default), with `--ctx-checkpoints 1 --cache-ram 0`.
"Starts" = the largest `--ctx-size` that loads and answers a short request (8k
steps); "filled" = context filled to 90% with real text (Python sources),
then a 200-token reply:

| Model | Short context prompt / generation (`llama-bench`) | Starts, `-ub 512` | Starts, `-ub 64` | Filled run |
|---|---:|---:|---:|---|
| UD-IQ3_XXS (10.9 GB) | 191 / 23.9 t/s | 112k | 112k | 64k: 127 / 18.4 t/s, 1.0 GB RAM free; **96k: 105 / 16.7 t/s**, 90 MB free |
| UD-IQ3_S (12.0 GB) | 186 / 22.8 t/s | 80k | 96k | **64k: 125 / 17.8 t/s**, 400 MB free; 80k with `-ub 64`: 95 / 17.0 t/s, 130 MB free |
| UD-IQ4_XS (14.4 GB) | 184 / 21.4 t/s | 24k | 24k | **16k: 161 / 19.7 t/s**, 80 MB free |

- The sizes in bold are the ones in the guide. Each step past the "starts"
  column failed to start.
- `--ctx-checkpoints 1`: Qwen3.8's recurrent layers are saved as context
  checkpoints of 150 MB each, by default up to 32 per slot (one every 8192
  tokens). In a single 64k request this saved ~150 MB (1015 vs 869 MB free);
  over a long chat they add up.
- `--cache-ram 0`: llama-server keeps up to 8 GB of old prompts in RAM by
  default. On this board that is the GPU's memory too.
- `-ub 64` (micro-batch) saves ~100–300 MB of compute buffers and costs ~25% prompt
  speed. Only worth it to squeeze in IQ3_S above 80k.
- **Going over the limit is not harmless.** A `--ctx-size` that does not fit makes
  the kernel's OOM killer kill other processes (NetworkManager, sshd, dbus,
  pipewire, the user's systemd, the sched-ext scheduler) before llama-server
  gives up. That happened even with llama-server at `oom_score_adj` 1000: its
  GPU memory is not freed fast enough when it is killed. Stay at tested sizes.
Qwen3.8 uses a hybrid architecture (`qwen35` in llama.cpp) in which only some
layers keep a classic KV cache, which is why long contexts fit at all. One 8k
step of q8_0 KV cache costs about 290 MB.

### Trimmed vocabulary

A Discord user's tip:
[ASCII-Condensed prune tools](https://github.com/bsaleh03/ASCII-Condensed-prune-tools)
remove tokens for scripts you don't use from the GGUF. Policy `P2` (ASCII plus
U+00A0–U+024F, the accented Latin letters) keeps 141,141 of 248,320 tokens:

| Model | File size | Starts, `-ub 512` | Starts, `-ub 64` | Filled run |
|---|---:|---:|---:|---|
| UD-IQ3_XXS-P2 | 10.9 → 10.4 GB | 120k (160 MB free) | – | 104k: not finished (VRM heat, see below) |
| UD-IQ3_S-P2 | 12.0 → 11.4 GB | 96k | 104k | **80k: 113 / 17.2 t/s**, 365 MB free |
| UD-IQ4_XS-P2 | 14.4 → 13.7 GB | 32k (305 MB free) | – | **24k: 157 / 19.2 t/s**, 343 MB free |

Measured with the VRAM carve-out at 256 MB (next section) and otherwise the same
setup as above. "120k" and "32k" are where the sweep stopped going up, not failures.

- About 3–4% faster generation, because the output layer is smaller.
- The default policy (`P1`, ASCII only) and `P1M` (ASCII plus math symbols)
  garble accented words: "cafĕ", "Belgiĕ", "geĭnteresseerd". `P2` gave the same
  answers as the untrimmed model in our checks. The tool keeps the 256 single-byte
  tokens, so a removed character can still be written byte by byte, but the model
  picked the wrong bytes ("é" became "ĕ").
- With `P2`, emoji, CJK, Cyrillic, Greek and math symbols have only that
  byte-by-byte route left.

### VRAM carve-out 256 MB

The BIOS reserves 512 MB of the 16 GB as "VRAM". With
[bc250_memcfg](https://github.com/fanoush/bc250_memcfg) it can be set to 256 MB
from Linux, no BIOS flash needed:

```bash
sudo ./bc250memcfg UMA_SIZE 256      # then reboot; UMA_SIZE 512 (or a CMOS clear) undoes it
```

It writes to the battery-backed CMOS. Results with `ttm.pages_limit=3670016`
left as it is:

- The system gets 252 MB more RAM.
- The GPU doesn't get more room: its limit is VRAM plus GTT, and GTT stays at
  14 GiB. Untrimmed UD-IQ3_S still starts at 80k and fails at 88k, the same
  as with 512 MB.
- The extra RAM is headroom for the rest of the system (130 vs 110 MB left in
  the 80k start test). That's why the trimmed-model sizes above say "use one
  step less at 512 MB" in the guide.

### Heat during long prompts

Prompt processing at full clock draws about 170 A on the GPU VRM (around 165 W
GPU power). On our test board, whose VRMs only have small heatsinks,
`GPU VRM Temp` went from 92 to 120 °C in 80 seconds and kept rising; the board
switches off at 140 °C. With the case fans on full speed it still reached
109 °C after 75 seconds from cold. The
long filled runs above take 2–14 minutes of prompt processing each, so
back-to-back runs heat-soak the VRMs. The IQ3_XXS-P2 104k run started right
after two such runs and the board switched off a minute in; the rerun was
stopped at 120 °C. How fast this happens depends on the cooling: a heatsink
that also covers the VRMs helps a lot. Short prompts don't matter: the VRMs
cool down in seconds.

A separate hang, without heat: trying a 112k start of UD-IQ3_S-P2 (`-ub 64`)
right after 104k had left only 287 MB free hung the board, instead of the OOM
kill described above. zram was the swap at the time. Since then the sweep stops
once less than 350 MB is left.

### beellama.cpp and KVarN KV cache

[beellama.cpp](https://github.com/Anbeeld/beellama.cpp) v0.4.9 (a llama.cpp
fork, Vulkan build) adds KVarN, a KV cache quantization with separate K and V
bit widths, and a full-precision "tail" for recent tokens. UD-IQ3_XXS, server
mode, VRAM 256 MB:

| | Prompt (pp512) | Generation (tg128) |
|---|---:|---:|
| llama.cpp, q8_0 | 190.8 t/s | 23.84 t/s |
| beellama, q8_0 | 188.8 | 23.81 |
| beellama, kvarn5/4 (also kvarn4/4, kvarn3/3) | 134.7 | 24.03 |

With `-ctk kvarn5 -ctv kvarn4 --kv-tail-tokens 1024` UD-IQ3_XXS-P2 starts at
184k context with 467 MB free (q8_0: 120k with 160 MB free); one 16k step costs
~340 MB instead of ~580 MB. Reading a prompt barely needs extra memory. But with
real text in the context it gets slow (136k context):

| Prompt in context | Prompt | Generation |
|---|---:|---:|
| 8k tokens | 56 t/s | 6.1 t/s |
| 16k tokens | 35 t/s | 4.4 t/s |

The fast KVarN kernels are CUDA-only for now; on Vulkan the speed drops with
every token in the context. Not usable here yet. Worth retesting when
beellama's Vulkan path gets faster.

### At full clock, and the gfx1013 llama.cpp fork

GPU fixed at 2100 MHz, `llama-bench -fa 1 -p 512 -n 128`:

| Build | Qwen3.8-27B IQ3_XXS prompt / generation | Qwen3.5-9B Q4_K_M prompt / generation |
|---|---:|---:|
| CachyOS `llama-cpp` package (cd959bae99) | 192.4 / 24.0 t/s | 582.6 / 59.3 t/s |
| llama.cpp master (32bdc3a89, 2026-11-14) | 198.6 / 23.9 t/s | 610.5 / 59.2 t/s |
| [TechMakesArt/llama.cpp-bc250](https://github.com/TechMakesArt/llama.cpp-bc250) (82fac30, June 2026) | cannot load the model | 472.5 / 55.2 t/s |

The fork's Vulkan changes for gfx1013 (K-quant tuning and a fused SwiGLU kernel)
gained ~49% against llama.cpp as it was in June; current llama.cpp is now faster
than the fork, the fork is too old for Qwen3.8, and it needs `-DLLAMA_OPENSSL=OFF`
to build with current OpenSSL. Use the packaged llama.cpp.

### MTP (multi-token prediction)

Qwen3.8 has built-in multi-token prediction heads. llama.cpp uses them for
speculative decoding: they guess the next tokens, and the full model checks
those guesses in one pass. The output is the same as without MTP. The heads
come as a separate file, `MTP/mtp-Qwen3.8-27B-Q4_0.gguf` (1.4 GB) in
`unsloth/Qwen3.8-27B-GGUF`, loaded with `--spec-type draft-mtp --model-draft …`.

CachyOS `llama-cpp` 0.9.0 + `ggml-vulkan`, governor running, server mode,
`llama-server` with the service-file settings (32k context, q8_0 KV), 400 tokens
per reply, thinking off. Each cell is generation speed at temperature 0 / 0.7,
and the percentage is the share of drafted tokens the model accepted (both
temperatures averaged):

| Drafted tokens (`--spec-draft-n-max`) | Code (Python function + tests) | Explanation | Short story | Average |
|---|---:|---:|---:|---:|
| no MTP | 23.3 / 23.3 t/s | 23.3 / 23.3 t/s | 23.3 / 23.3 t/s | 23.3 t/s |
| 1 | 29.3 / 28.8 (92%) | 26.9 / 26.9 (77%) | 26.3 / 24.7 (68%) | 27.2 t/s |
| **2** | **31.6 / 30.4 (84%)** | 26.5 / 27.5 (66%) | 25.4 / 23.8 (57%) | **27.5 t/s** |
| 3 (default) | 28.0 / 28.6 (78%) | 21.7 / 19.8 (48%) | 19.7 / 18.8 (42%) | 22.8 t/s |

- 2 is best. With 3, too many guesses get rejected on prose, and it ends up
  slower than without MTP.
- With a 20,600-token prompt: prompt 166 → 156 t/s (−6%), generation
  21.1 → 24.8 t/s (+18%).
- Memory: about 1.3 GB more. The 32k context still fits, but with almost no
  free RAM left (about 60 MiB available, about 200 MiB more swap used). Keep the board in
  server mode while it runs.
- A q8_0 KV cache for the draft (`-ctkd q8_0 -ctvd q8_0`) made no difference.

## LLM: Inkling-2-Mini

Inkling-2-Mini (Thinking Machines, 26B mixture-of-experts, about 3.4B active per token) as Unsloth's
`Inkling-2-Mini-UD-IQ3_XXS.gguf` (10.85 GiB), all on the GPU. llama.cpp 1.0.0 (the CachyOS package) has no
`inkling2` support; this is [llama-inkling2-vulkan](https://github.com/Trecto34/llama-inkling2-vulkan) v0.2
(`e734ca0`, llama.cpp with fused Vulkan shaders for this model), built from source. 2026-11-22, game session
stopped, `llama-bench -ngl 99 -fa 1 -p 512 -n 128`:

| Machine | Prompt (512 tokens) | Generation |
|---|---:|---:|
| BC-250, 40 CUs, governor running | 444.9 t/s | 47.2 t/s |
| PS5 Pro (PS5-CachyOS, `7.3.5-pc8fe-bc1`) | 686.2 t/s | 59.2 t/s |
| the fork's release notes (BC-250) | 432.7 t/s | 47.1 t/s |

About 2.3x the prompt speed and 2x the generation of Qwen3.8-27B IQ3_XXS on the same board (192 / 24 t/s).
A short test question with `--temp 0` got a correct answer.

### Micro-batch and context

The KV cache is small: 8 global-attention layers keep the full context (136 MB at 8k, q8_0), the other 40 a
1024-token sliding window. What grows is the GPU compute buffer, with context *times* micro-batch (`-ub`):
1.4 GB at 8k with `-ub 512`. A smaller micro-batch keeps it down, at the cost of prompt speed:

| `-ub` | 32 | 64 | 128 | 256 | 512 |
|---|---:|---:|---:|---:|---:|
| BC-250, prompt t/s | 164 | 170 | 258 | 355 | 445 |
| PS5 Pro, prompt t/s | 228 | 242 | 374 | 514 | 676 |

Server mode (`llama-server -fa on -ctk q8_0 -ctv q8_0 --parallel 1 --ctx-checkpoints 1 --cache-ram 0`),
started, one short request, then `MemAvailable`:

| Context | `-ub` | Compute buffer | BC-250 | PS5 Pro |
|---:|---:|---:|---:|---:|
| 8k | 512 | 1400 MB | 1.5 GB left | 1.5 GB left |
| 16k | 512 | | 0.3 GB left | did not fit (OOM kill) |
| 16k | 256 | 973 MB | 2.0 GB left | 1.6 GB left |
| 32k | 512 | | did not fit (OOM kill) | |
| 32k | 128 | 890 MB | 1.6 GB left | 1.5 GB left |
| 64k | 64 | 847 MB | 1.1 GB left | 1.4 GB left |
| 96k | 64 | 1291 MB | 0.1 GB left | |

Generation is the same at every micro-batch (about 45 t/s on the BC-250 in these server runs). Not measured
yet: a filled context, and the vision part (`mmproj`).

## Images: SDXL in ComfyUI

SDXL base 1.0, 1024×1024, one image, after the first, GPU at 1200 MHz (at a
fixed 2100 MHz the Lightning setup takes 20.3 s):

| Setup | Time per image | Per step |
|---|---:|---:|
| 25 steps, cfg 7, `dpmpp_2m` / `karras`, ComfyUI defaults | 153 s | 5.76 s |
| 25 steps, with TunableOp | 134 s | 4.95 s |
| **SDXL-Lightning 8 steps, cfg 1, with TunableOp** | **29 s** | 1.95 s |

With cfg 1 there is no separate negative-prompt pass, so each Lightning step
costs half a normal one, and there are 3x fewer of them. The rest of the 29 s
is mostly decoding the image (VAE).

What we tried, per SDXL step at 1024×1024 (25-step setup, 1200 MHz):

| Change | Per step | |
|---|---:|---|
| ComfyUI defaults (sub-quadratic attention) | 5.77 s | |
| `--use-pytorch-cross-attention` | 5.99 s | attention is not the bottleneck |
| `--use-split-cross-attention` | 5.86 s | |
| `PYTORCH_TUNABLEOP_ENABLED=1` | **4.95 s** | the one setting that helps |
| + MIOpen for convolutions (`COMFYUI_ENABLE_MIOPEN=1`) | 5.12 s | |
| + MIOpen with full search (`MIOPEN_FIND_MODE=1`) | 5.12 s | |
| fp32 instead of fp16 | 5.51 s | |
| fp16 VAE (`sdxl-vae-fp16-fix` + `--fp16-vae`) | no change per image | ComfyUI's bf16 VAE is as fast |

A profile of one step shows why: 61% of the time is matrix multiplies, which
rocBLAS runs on its generic gfx1013 kernels (there are no tuned ones for this
GPU yet), and 18% convolutions. TunableOp picks the fastest of the available
kernels per size; the rest needs tuned kernels for gfx1013.

TunableOp writes its results (`tunableop0.csv`: the GPU index is appended to the
name) only when the process exits normally. Stopped with Ctrl-C, ComfyUI saves
them and the next start needs no tuning (27 s for its first image, model loading
included); killed with SIGTERM it saves nothing and tunes again.

The same prompt with SDXL-Lightning, 8 steps (29 s), and plain SDXL, 25 steps (134 s):

| SDXL-Lightning, 8 steps | SDXL, 25 steps |
|---|---|
| ![SDXL-Lightning](images/ai/sdxl-lightning-8step.jpg) | ![SDXL](images/ai/sdxl-25step.jpg) |
