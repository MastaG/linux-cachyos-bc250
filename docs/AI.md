# Local AI on the BC-250

Two setups, both the fastest we measured on the board
([numbers and what else we tried](AI-BENCHMARKS.md)):

- **Chat (LLM):** Qwen3.8-27B with llama.cpp: about 27 tokens/s (31 on code), 32k context.
- **Faster chat (LLM):** Inkling-2-Mini with a llama.cpp fork: about 47 tokens/s, 32k context.
- **Images:** ComfyUI with SDXL-Lightning: a 1024×1024 image in about 20 s.

Each needs most of the board's memory, so run one at a time.

## Kernel parameters

| Parameter | Why |
|---|---|
| `ttm.pages_limit=3670016` | Lets the GPU use up to 14 GB of the board's memory (the default is about half). Without it the 27B model does not fit. It helps the PS5 emulator too. |
| `amdgpu.sched_policy=2` | Needed for ROCm (ComfyUI), see [ROCm](ROCM.md). Not needed for chat. |
| `amdgpu.bc250_cc_write_mode=3` | Optional: unlocks all 40 CUs ([details](PATCHES.md#optional-40-cu-unlock)). All numbers here are measured with it. |

On CachyOS with Limine, add them inside the quotes of the `KERNEL_CMDLINE[default]+="…"`
line in `/etc/default/limine` (skip any you already have), then:

```bash
sudo limine-mkinitcpio
sudo reboot
cat /proc/cmdline                 # check they are there
```

## Before you start: server mode

The GPU shares the board's 16 GB with the system. Stop the game session while
you use these models:

```bash
sudo systemctl stop display-manager      # stop Steam and the display
sudo systemctl start display-manager     # back to game mode (or reboot)
```

Keep the GPU clock governor running (`cyan-skillfish-governor-smu`, see the
[README](../README.md#cyan-skillfish-governor-recommendations)): without it the
GPU stays at a low clock and everything below is about 35% slower. Don't use
`systemctl isolate multi-user.target` instead of the commands above: it stops
the governor too.

If you work over SSH, also run this once, or your services stop when you log out:

```bash
sudo loginctl enable-linger $USER
```

## Chat: Qwen3.8-27B

```bash
sudo pacman -S llama-cpp ggml-vulkan
mkdir -p ~/models && cd ~/models
curl -LO https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-IQ3_XXS.gguf   # 10.9 GB
curl -LO https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/MTP/mtp-Qwen3.8-27B-Q4_0.gguf  # 1.4 GB
```

Create `~/.config/systemd/user/llama-server.service`:

```ini
[Unit]
Description=llama.cpp server (Qwen3.8-27B)

[Service]
ExecStart=/usr/bin/llama-server --model %h/models/Qwen3.8-27B-UD-IQ3_XXS.gguf \
    --n-gpu-layers 99 --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 \
    --ctx-size 32768 --parallel 1 --jinja --host 0.0.0.0 --port 8080 \
    --spec-type draft-mtp --model-draft %h/models/mtp-Qwen3.8-27B-Q4_0.gguf \
    --n-gpu-layers-draft 99 --spec-draft-n-max 2
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now llama-server
```

Open `http://<board-ip>:8080` for a chat page. Port 8080 is also an
OpenAI-compatible API (`/v1/chat/completions`) for Open WebUI, SillyTavern or
your own scripts.

- Qwen3.8 thinks before it answers. With an API, give it `max_tokens` of 2000+
  or the answer may come back empty, or turn thinking off per request with
  `"chat_template_kwargs": {"enable_thinking": false}`.
- Like any local model it can state wrong facts with confidence. Check what matters.
- The `--spec-type draft-mtp` lines use the model's multi-token prediction
  heads to guess 2 tokens ahead. It doesn't change the answers, and it makes
  replies about 18% faster (more on code, less on prose). It uses 1.3 GB more memory: if
  you need that memory, remove those two lines and the trailing `\` before them.
- Use the Vulkan backend as above: it is faster here than ROCm and needs no extra setup.
- Want it faster rather than smarter? `Qwen3.5-9B-Q4_K_M.gguf` (5.7 GB, from
  `unsloth/Qwen3.5-9B-GGUF`) runs at about 60 tokens/s with the same service file.

### More context or a better quant

The setup above is the fastest. If you'd rather have a longer context or a
better quant (more accurate answers), drop the MTP lines and use one of these
instead. Each was tested with the context filled to 90%:

| Model file (from `unsloth/Qwen3.8-27B-GGUF`) | `--ctx-size` | Speed, short / full context |
|---|---:|---:|
| `Qwen3.8-27B-UD-IQ3_XXS.gguf` (10.9 GB) | `98304` | 24 / 17 tokens/s |
| `Qwen3.8-27B-UD-IQ3_S.gguf` (12.0 GB) | `65536` | 23 / 18 tokens/s |
| `Qwen3.8-27B-UD-IQ4_XS.gguf` (14.4 GB) | `16384` | 21 / 20 tokens/s |

Add `--ctx-checkpoints 1 --cache-ram 0` to the `ExecStart` line. By default
llama-server keeps up to 32 snapshots of 150 MB each, and up to 8 GB of old
prompts in RAM, which the GPU needs here.

Don't go above these sizes. A context that doesn't fit doesn't just fail to start: the
kernel then runs out of memory and kills other services (network, SSH, audio)
before llama-server. Sometimes the whole board hangs and needs a power cycle.

### Even more context: trim the vocabulary

Qwen3.8 knows about 248,000 tokens for all the world's scripts. If you only
chat in English and other Latin-alphabet languages, you can remove the rest from
the model file. That frees about 0.5–0.7 GB for context and makes replies about
3% faster. With the [ASCII-Condensed prune tools](https://github.com/bsaleh03/ASCII-Condensed-prune-tools):

```bash
git clone https://github.com/bsaleh03/ASCII-Condensed-prune-tools ~/prune-tools
python -m venv ~/prune-venv && ~/prune-venv/bin/pip install gguf numpy
cd ~/models
~/prune-venv/bin/python ~/prune-tools/prune_vocab.py \
    Qwen3.8-27B-UD-IQ3_S.gguf Qwen3.8-27B-UD-IQ3_S-P2.gguf --policy P2
```

Use `--policy P2` (ASCII plus accented Latin letters). With the default (ASCII
only) or `P1M`, words like "café" or "België" came out garbled in our tests. The
model can still spell a removed character byte by byte, but it often picks the
wrong bytes. With `P2` the same goes for emoji, Chinese, Cyrillic, Greek and math
symbols.

| Trimmed model file | `--ctx-size` | Speed, full context |
|---|---:|---:|
| `Qwen3.8-27B-UD-IQ3_S-P2.gguf` (11.4 GB) | `81920` | 17 tokens/s |
| `Qwen3.8-27B-UD-IQ4_XS-P2.gguf` (13.7 GB) | `24576` | 19 tokens/s |

Same flags as in the table above (`--ctx-checkpoints 1 --cache-ram 0`, no MTP).
These two were tested with the VRAM carve-out set to 256 MB
([details](AI-BENCHMARKS.md#vram-carve-out-256-mb)), which leaves the system
250 MB more RAM. With the default 512 MB, use one step less (`73728` and `16384`).

### Heat: long prompts

Reading a long prompt (tens of thousands of tokens, such as a long document
or a big codebase) keeps the GPU at full power for minutes, and the GPU's
voltage regulators (VRMs) get hot. With small VRM heatsinks we measured
92 → 120 °C in 80 seconds. The board switches itself off at 140 °C. Normal chat is fine: short prompts don't load the GPU long
enough, and the VRMs cool down within seconds between replies.

Check with `sensors` (`GPU VRM Temp`). If it goes above about 110 °C, add
airflow over the VRM heatsinks, or don't feed it very long prompts.

## Faster chat: Inkling-2-Mini

[Inkling-2-Mini](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF) (Thinking Machines) is a
26B mixture-of-experts model: only about 3.4B of its parameters work on each token, so it runs about
twice as fast as Qwen3.8-27B at a similar file size. On the BC-250 (40 CUs): **445 tokens/s reading a prompt and
47 tokens/s writing**.

The packaged llama.cpp can't run it yet (the `inkling2` architecture is not in it). Trecto34's
[llama-inkling2-vulkan](https://github.com/Trecto34/llama-inkling2-vulkan) is llama.cpp with that
support and Vulkan shaders written for this model. Build it yourself:

```bash
sudo pacman -S --needed cmake ninja git vulkan-headers spirv-headers shaderc glslang
git clone https://github.com/Trecto34/llama-inkling2-vulkan.git ~/llama-inkling2-vulkan
cd ~/llama-inkling2-vulkan
git checkout e734ca0          # v0.2-vulkan, the version measured here
cmake -B build -G Ninja -DGGML_VULKAN=ON -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build --target llama-server llama-cli llama-bench

mkdir -p ~/models && cd ~/models
curl -LO https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/main/Inkling-2-Mini-UD-IQ3_XXS.gguf   # 11.7 GB
```

Run it with the same kind of service file as above, for example
`~/.config/systemd/user/llama-inkling.service`. Stop the Qwen3.8 service first: only one model fits at a time.

```ini
[Unit]
Description=llama.cpp server (Inkling-2-Mini)

[Service]
ExecStart=%h/llama-inkling2-vulkan/build/bin/llama-server \
    --model %h/models/Inkling-2-Mini-UD-IQ3_XXS.gguf \
    --n-gpu-layers 99 --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 \
    --ctx-size 32768 --ubatch-size 128 --parallel 1 --ctx-checkpoints 1 --cache-ram 0 \
    --host 0.0.0.0 --port 8080
Restart=on-failure

[Install]
WantedBy=default.target
```

**Set `--ubatch-size` with the context size.** In this build the GPU's work buffer grows with the
context *times* the micro-batch, not the KV cache (that is small: 136 MB at 8k). Pick a row:

| `--ctx-size` | `--ubatch-size` | Prompt speed | Memory left |
|---:|---:|---:|---:|
| `8192` | `512` (default) | 445 t/s | 1.5 GB |
| `16384` | `256` | 355 t/s | 2.0 GB |
| **`32768`** | **`128`** | **258 t/s** | **1.6 GB** |
| `65536` | `64` | 170 t/s | 1.1 GB |

Each row starts and answers a short request; the context was not filled with text. The micro-batch
only changes how fast prompts are read: writing stays at about 47 tokens/s.

- With the default micro-batch, 16k left only 0.3 GB and 32k was killed for lack of memory.
  96k with `--ubatch-size 64` starts, but leaves 0.1 GB: too little.
- Long prompts heat the VRMs here as with Qwen ([Heat](#heat-long-prompts)).

- It thinks before it answers by default, so give API requests room (`max_tokens` 1000+).
- Like any local model it can state wrong facts with confidence. Check what matters.

## Images: ComfyUI with SDXL-Lightning

Needs `amdgpu.sched_policy=2` (see [Kernel parameters](#kernel-parameters)).

```bash
sudo pacman -S bc250-pytorch
bc250-pytorch-check                  # should end with "OK"

git clone https://github.com/comfyanonymous/ComfyUI ~/ComfyUI
cd ~/ComfyUI
/opt/bc250-pytorch/bin/python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt

curl -L -o models/checkpoints/sd_xl_base_1.0.safetensors \
  https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors     # 6.9 GB
curl -L -o models/loras/sdxl_lightning_8step_lora.safetensors \
  https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_8step_lora.safetensors         # 0.4 GB
```

The clock governor can't see this kind of GPU work and would leave the GPU at
its lowest clock, so set a fixed clock while you generate images, then start
ComfyUI:

```bash
sudo busctl --system set-property com.cyanskillfish.Governor /com/cyanskillfish/Governor \
  com.cyanskillfish.Governor.PerformanceMode Enabled b true
sudo busctl --system call com.cyanskillfish.Governor /com/cyanskillfish/Governor \
  com.cyanskillfish.Governor.PerformanceMode SetFixedFrequency u 2100    # or your config's max

cd ~/ComfyUI
PYTORCH_TUNABLEOP_ENABLED=1 PYTORCH_TUNABLEOP_FILENAME=$HOME/ComfyUI/tunableop.csv \
  venv/bin/python main.py --listen 0.0.0.0
```

Open `http://<board-ip>:8188`. In the default workflow:

1. *Load Checkpoint*: `sd_xl_base_1.0.safetensors`.
2. Add a **LoraLoaderModelOnly** node between *Load Checkpoint* and *KSampler*,
   with `sdxl_lightning_8step_lora.safetensors`.
3. *KSampler*: steps **8**, cfg **1.0**, sampler **euler**, scheduler **sgm_uniform**.
4. *Empty Latent Image*: **1024 × 1024**.

**The first image takes about 8 minutes**: TunableOp measures the GPU's
fastest settings for every size the model uses. They are saved (as
`tunableop0.csv`) when you stop ComfyUI with Ctrl-C, so do that rather than
killing it; after that every image takes about 20 s, also after a restart.
After a `bc250-pytorch` update the first image is slow once more.

When you are done, stop ComfyUI with **Ctrl-C** and give the clock back to the
governor:

```bash
sudo busctl --system set-property com.cyanskillfish.Governor /com/cyanskillfish/Governor \
  com.cyanskillfish.Governor.PerformanceMode Enabled b false
```

Don't `pip install torch` into the venv, and remove any line in a custom node's
requirements that pins a torch version: that would replace the BC-250 build
with a CUDA one.

![SDXL-Lightning, 8 steps](images/ai/sdxl-lightning-8step.jpg)

*"a cozy cabin in a snowy pine forest at dusk, warm light in the windows,
photorealistic, detailed": SDXL-Lightning, 8 steps.*
