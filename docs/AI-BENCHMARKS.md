# BC-250 AI benchmarks

The measurements behind the setups in [AI.md](AI.md): one board, 2026-11-14,
CachyOS with a kernel from this repository, all 40 CUs unlocked
(`amdgpu.bc250_cc_write_mode=3`), `amdgpu.sched_policy=2`, the default 512 MB
VRAM carve-out, game session stopped.

## LLM: Qwen3.8-27B

Qwen3.8-27B, Unsloth `UD-IQ3_XXS` (10.9 GB, 3.06 bits per weight), all layers on
the GPU, `llama-bench`:

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

How much context fits (`--parallel 1`, q8_0 KV cache, game session stopped):

| `--ctx-size` | GPU memory | RAM left over |
|---:|---:|---:|
| 32768 | 11.2 GB | 3.1 GB |
| 65536 | 12.5 GB | 1.8 GB |
| 98304 | 13.5 GB | 0.7 GB |
| 131072 | fails: `Not enough memory for command submission` | |

32k is the comfortable setting; 64k works if nothing else runs. Running out
only fails that request (`vk::DeviceLostError` in llama.cpp); the GPU itself
recovers without a reset. Leave `--parallel` at 1 for one user: the default of 4
slots splits the context between them.

Qwen3.8 uses a hybrid architecture (`qwen35` in llama.cpp) in which only some
layers keep a classic KV cache, which is why long contexts fit at all.

## Images: SDXL in ComfyUI

SDXL base 1.0, 1024×1024, one image, after the first:

| Setup | Time per image | Per step |
|---|---:|---:|
| 25 steps, cfg 7, `dpmpp_2m` / `karras`, ComfyUI defaults | 153 s | 5.76 s |
| 25 steps, with TunableOp | 134 s | 4.95 s |
| **SDXL-Lightning 8 steps, cfg 1, with TunableOp** | **29 s** | 1.95 s |

With cfg 1 there is no separate negative-prompt pass, so each Lightning step
costs half a normal one, and there are 3x fewer of them. The rest of the 29 s
is mostly decoding the image (VAE).

What we tried, per SDXL step at 1024×1024 (25-step setup):

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

The same prompt with SDXL-Lightning, 8 steps (29 s), and plain SDXL, 25 steps (134 s):

| SDXL-Lightning, 8 steps | SDXL, 25 steps |
|---|---|
| ![SDXL-Lightning](images/ai/sdxl-lightning-8step.jpg) | ![SDXL](images/ai/sdxl-25step.jpg) |
