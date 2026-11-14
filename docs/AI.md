# Local AI on the BC-250

Two setups, both the fastest we measured on the board
([numbers and what else we tried](AI-BENCHMARKS.md)):

- **Chat (LLM):** Qwen3.8-27B with llama.cpp: about 24 tokens/s, 32k context.
- **Images:** ComfyUI with SDXL-Lightning: a 1024×1024 image in about 20 s.

Each needs most of the board's memory, so run one at a time.

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
```

Create `~/.config/systemd/user/llama-server.service`:

```ini
[Unit]
Description=llama.cpp server (Qwen3.8-27B)

[Service]
ExecStart=/usr/bin/llama-server --model %h/models/Qwen3.8-27B-UD-IQ3_XXS.gguf \
    --n-gpu-layers 99 --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 \
    --ctx-size 32768 --parallel 1 --jinja --host 0.0.0.0 --port 8080
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
- Use the Vulkan backend as above: it is faster here than ROCm and needs no extra setup.
- Want it faster rather than smarter? `Qwen3.5-9B-Q4_K_M.gguf` (5.7 GB, from
  `unsloth/Qwen3.5-9B-GGUF`) runs at about 60 tokens/s with the same service file.

## Images: ComfyUI with SDXL-Lightning

Needs `amdgpu.sched_policy=2` on the kernel command line (see [ROCm](ROCM.md)).

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
