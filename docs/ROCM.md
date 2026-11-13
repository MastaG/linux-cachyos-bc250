# Experimental ROCm / KFD support

On GFX1013 the normal gfx10 PASID TLB flush finds no VMID for a KFD process, so a compute TLB invalidation never happens: `hipFree` unmaps, `hipMalloc` reuses the address with a new physical page, and the GPU keeps reading through the old translation. Kernels then return wrong data with no error. This repository's kernels carry two ways around it, one for each KFD scheduling mode.

## Recommended: no hardware scheduling (`sched_policy=2`)

```text
amdgpu.sched_policy=2
```

Without the hardware scheduler a process keeps one fixed VMID while it has queues. `0025-bc250-kfd-nohws-vmid-flush.patch` flushes that VMID directly on every KFD map and unmap (a legacy, type-0 flush on the GFX hub), the way amdgpu did before PASID flushes existed. When a process gets its VMID, and when it gives it back, the stock code flushes it as well, so no stale translation survives a reuse. `0028-bc250-gmc-kfd-vmid-mmio-flush.patch` sends these flushes over MMIO like the PASID flushes: through the KIQ they stalled for seconds each when several compute processes ran at once (`failed to write reg 28b4 wait reg 28c6`). Nothing else needs to be set; `bc250_flush_by_runlist` does nothing in this mode and can stay at `0`.

This is the configuration that holds up under sustained training ([issue #13](https://github.com/MastaG/linux-cachyos-bc250/issues/13), stock ROCm 7.2.4 with a gfx1013 rocBLAS and a native PyTorch build):

- a CPU-referenced validation suite passes: fp32/fp16/bf16 GEMM against float64 over 11 shapes, layer_norm and rms_norm forward and backward, 50 optimizer steps agreeing with the CPU, 100 allocation/dispatch cycles;
- 500 steps of LoRA fp16 training (256x2 tokens) ran with no preemption failure, GPU reset or page fault, and the loss went down;
- the same run under `sched_policy=0` (below) locked the board within seconds.

That run had 36 CUs unlocked for dispatch by a userspace tool after boot, but KFD counts CUs once, when the driver loads, so ROCm saw the fused 24. For KFD to see unlocked CUs they have to be unlocked by the kernel: `amdgpu.bc250_cc_write_mode=3` (all 40) or `amdgpu.bc250_cc_wgp_mask` (per shader array), see [Optional 40 CU unlock](PATCHES.md#optional-40-cu-unlock).

Limits of this mode: queues are mapped statically, so there is no oversubscription (only as many KFD processes and queues as there are free compute VMIDs and queue slots), and a kernel that never finishes can still hang the GPU. Moving a process's memory (eviction) still preempts its queues; that has not caused a failure so far.

`sched_policy=2` applies to the whole board, games included; see [Optional AMDGPU scheduler tuning](../README.md#optional-amdgpu-scheduler-tuning) for what it does there.

## Experimental: runlist rebuild under hardware scheduling (`sched_policy=0`)

`0008-bc250-kfd-flush-tlb-by-runlist.patch` is based on the BC-250 ROCm investigation by GabriWar.  
Under KFD hardware scheduling the HWS path does not populate the `ATC_VMID*_PASID_MAPPING` table that the PASID flush uses. Rebuilding an active HWS runlist has been measured to clear the stale translation state and is therefore provided as an experimental workaround.

**It is not stable under sustained load.** Every rebuild preempts every active compute queue. During training that happens on every allocation and free while long dispatches are running; sooner or later the MEC firmware gives up on one preemption, the kernel cannot reset that single queue, and amdgpu starts a full GPU reset, which does not recover on this board. The machine then stops answering and needs a power cycle. The kernel log shows, if it gets to disk at all:

```text
Queue preemption failed for queue with doorbell_id: ...
BC-250: runlist rebuild flush failed (-62)
GPU reset begin!. Source:  4
BC-250: runlist rebuild flush failed (-5)
Failed to restore process queues
```

`-62` (ETIME) is the abandoned preemption itself. The later `-5` (EIO) lines are map/unmap calls that arrive while the reset holds the queue manager; they are a consequence, not a second fault. Raising `queue_preemption_timeout_ms` does not help: the firmware gives up on its own wait before that timeout applies. Use this mode to investigate the HWS path, not to train.

The workaround is **disabled by default** and restricted to PCI device `0x13FE` with GFX IP `10.1.3`. It also refuses to run under non-HWS scheduling or MES.  
`bc250_flush_by_runlist` is a bitmask of the sites where the runlist is rebuilt:

| Value | Rebuild on |
|---|---|
| `0` | nowhere (default) |
| `1` | unmap: the KFD unmap ioctl and SVM unmap |
| `2` | map: the KFD map ioctl and SVM map |
| `3` | both (needed for correct results under HWS) |

The map side matters: with the rebuild only on unmap, a fresh mapping can still be read through a stale translation, so a kernel returns wrong data from its second dispatch onward with no error ([akandr/bc250-rocm](https://github.com/akandr/bc250-rocm)). Enable it at boot only for ROCm/KFD testing under HWS:

```text
amdgpu.sched_policy=0 amdgpu.bc250_flush_by_runlist=3
```

Or enable/disable it at runtime while HWS is already active:

```bash
echo 3 | sudo tee /sys/module/amdgpu/parameters/bc250_flush_by_runlist
echo 0 | sudo tee /sys/module/amdgpu/parameters/bc250_flush_by_runlist
```

The helper only rebuilds an already-active runlist, preserving the scheduler state instead of accidentally activating an inactive runlist.

## Both modes

The other half of the fix, not sending the PASID TLB flush through the KIQ, needs no parameter here: `0006-gfx1013-pasid-tlb-invalidation.patch` always routes GFX1013's PASID flushes over MMIO (`flush_pasid_uses_kiq = false` on GC 10.1.3), and also issues them as a semaphore-guarded type-0 invalidation on the GFX hub. That is what `amdgpu.bc250_flush_pasid_kiq=0` selects in other trees ([ROCm/TheRock#9221](https://github.com/ROCm/TheRock/issues/9221)); the boot log shows `GFX1013/BC-250: using MMIO PASID TLB flushes`.

Other `bc250_*` parameters in these kernels are not for ROCm:

| Parameter | Default | For ROCm |
|---|---|---|
| `bc250_gfx_queues` | `1` | graphics rings only; leave it |
| `bc250_gfx_eop_events` | `0` | end-of-pipe interrupts of graphics work; leave it |
| `bc250_mtype_rw` | `1` | only affects buffers that ask for `AMDGPU_VM_MTYPE_RW`, which KFD does not do on gfx10; no effect |
| `bc250_tlb_flush_type` | `-1` | GFX1013's PASID flushes and the no-HWS VMID flush are already type 0; leave it |

## Other kernel fixes

`0009-amdgpu-ttm-null-page-guard.patch` is separate from the TLB workaround. TTM allocation failures can legitimately leave NULL entries in a partially populated page vector, while AMDGPU's unpopulate path dereferenced every entry before calling `ttm_pool_free()`. The patch skips NULL entries during the `page->mapping` cleanup; the TTM free path (`ttm_pool_free_range()`, checked against Linux 7.3) already skips those sparse entries.  
This does not fix the compute fault that caused a partial allocation; it prevents that failure from escalating into a kernel NULL-pointer panic during cleanup.

ROCm userspace still requires additional GFX1013-specific work outside this kernel repository. These kernel patches alone should not be read as complete ROCm support.

## ROCm userspace requirements

GabriWar's working stack uses stock ROCm userspace, but adds a GFX1013-specific rocBLAS/Tensile kernel library and a PyTorch build compiled natively for `gfx1013`. The rocBLAS library files are installed under `/opt/rocm/lib/rocblas/library`; without GFX1013 code objects, even basic rocBLAS workloads such as matrix multiplication cannot run correctly on the BC-250.

The current reference setup also uses a small set of runtime settings, including `HSA_ENABLE_SDMA=0`, `GPU_PINNED_MIN_XFER_SIZE=16384` and `TORCH_BLAS_PREFER_HIPBLASLT=0`. Earlier serialization/warm-up workarounds were removed after testing showed they did not address the underlying stale-translation problem.

The userspace side is still experimental and can evolve independently of these kernel patches. For the current build instructions, GFX1013 rocBLAS/Tensile artifacts, PyTorch notes, validation tools and ongoing ROCm investigation, see [GabriWar/bc250-rocm-working](https://github.com/GabriWar/bc250-rocm-working).

