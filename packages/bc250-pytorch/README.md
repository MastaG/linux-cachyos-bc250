# PyTorch on the BC-250

`bc250-pytorch` puts PyTorch 2.13 (+ torchvision, torchaudio) with ROCm built for
the BC-250 GPU (gfx1013) in `/opt/bc250-pytorch`, inside its own Python 3.12.
It does not use or change the system Python or any system ROCm packages, so
CachyOS updates don't break it.

## Before you start

1. ROCm compute is only stable with `amdgpu.sched_policy=2` on the kernel
   command line. This changes GPU scheduling for everything, games included.
2. Your user must be in the `render` group (`sudo usermod -aG render $USER`,
   then log out and in).
3. Check: `bc250-pytorch-check` — it reports both of the above and runs a small
   matrix multiply and convolution on the GPU.

## Using it in an app (ComfyUI as example)

Make the app's venv *on top of* the bc250 Python, with `--system-site-packages`,
so torch comes from /opt and only the app's own packages go into the venv:

```
git clone https://github.com/comfyanonymous/ComfyUI ~/ComfyUI
cd ~/ComfyUI
/opt/bc250-pytorch/bin/python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt     # torch/torchvision are "already satisfied"
venv/bin/python main.py
```

With uv: `uv venv --python /opt/bc250-pytorch/bin/python3 --system-site-packages`.

For a quick script without a venv: `bc250-python myscript.py`.

## Things to know

- Don't `pip install torch` (or anything that pins `torch==<other version>`) in the
  venv: pip would download the CUDA build from PyPI over the top. If an app's
  requirements pin torch, remove that line.
- System Python packages (`pacman -S python-*`) can't be used from this Python:
  they're built for the system's Python version. Install what you need in the venv.
- No flash attention, no hipBLASLt, no composable_kernel and no Triton
  (`torch.compile` on the GPU) on gfx1013: these don't support this GPU.
- The settings the BC-250 needs (`HSA_ENABLE_SDMA=0`,
  `GPU_PINNED_MIN_XFER_SIZE=16384`, `TORCH_BLAS_PREFER_HIPBLASLT=0`) are applied
  automatically when this Python starts; set one yourself to override it.
- For LLMs, llama.cpp / Ollama / KoboldCpp with Vulkan are usually the easier
  route and don't need ROCm at all.
