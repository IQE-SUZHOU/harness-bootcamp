================================================================================
GPU HANG DEBUG REPORT — llama-bench on AMD Strix Halo (gfx1151) WSL2
================================================================================

1. VERDICT: REPRODUCED

   The ROCm component batch 63 (libhsa-runtime64.so.1.21.0 + rocdxg-roct 1.1.0,
   dated 2026-10-10) on this gfx1151 node triggered a GPU hang during
   llama-bench execution with Qwen1.5-7B q5_k_m. The reproduction script
   (run.log steps 1–10) confirms deterministic failure: rc=134 (SIGABRT),
   FaultMonitorThread detected a 30-second GPU stall, and the ROCm runtime
   returned HSA_STATUS_ERROR_MEMORY_APERTURE_VIOLATION.

2. 故障签名 (Fault Signature)

   Source: bench_1.log, line 1068
     pid:11560 tid:0x7ab55affd6c0 [FaultMonitorThread] GPU stall detected: rptr=64 wptr=66 stalled for 30000ms — possible device memory fault

   Source: bench_1.log, line 1072–1073
     *** GPU HANG ANALYSIS - VGPU(0x5680391e8080) Queue(0x7a2200830000)
     VGPU(0x5680391e8080) Queue(0x7a2200830000). Couldn't find the hang AQL packet!

   Source: bench_1.log, line 1077
     :0:rocdevice.cpp            :4509: 1987495831 us:  Callback: Queue 0x7a2200831000 aborting with error : HSA_STATUS_ERROR_MEMORY_APERTURE_VIOLATION: The agent attempted to access memory beyond the largest legal address. code: 0x29 [host: D-002-G2-gfx1151, GPU index: 0, kernel: <not identified>]

   Source: dmesg_after_1.log, line 685–690
     [1627.282782] misc dxg: dxgk: dxgkio_escape: Ioctl failed: -75    (×6 occurrences)

   Source: dmesg_after_1.log, line 731–732
     [1987.532217] llama-bench: llama-bench: potentially unexpected fatal signal 6.
     [1987.532226] CPU: 16 UID: 1000 PID: 12679 Comm: llama-bench Not tainted 6.18.33.2-microsoft-standard-WSL2

3. 根因分析 (Root Cause Analysis)

   Component: librocdxg.so.1.1.0 (rocdxg-roct 1.1.0, batch 63) + libhsa-runtime64.so.1.21.0
   GPU: AMD Radeon 8060S Graphics (gfx1151), Strix Halo APU, ~66 GiB VRAM
   Platform: WSL2 kernel 6.18.33.2-microsoft-standard-WSL2

   Evidence chain:

   a) GPU Stall Detection (bench_1.log:1068)
      The FaultMonitorThread (built into librocdxg) observed that the GPU
      queue ring buffer read pointer (rptr=64) was stuck behind the write
      pointer (wptr=66) for 30,000ms — a classic GPU hang signal. The
      stall occurred during llama_kv_cache layer initialization (layers
      0–31), specifically when allocating the ~1 GiB KV cache buffer on
      the ROCm device.

   b) Memory Aperture Violation (bench_1.log:1077)
      The HSA runtime callback in rocdevice.cpp:4509 reported
      HSA_STATUS_ERROR_MEMORY_APERTURE_VIOLATION (code 0x29): "The agent
      attempted to access memory beyond the largest legal address." This
      indicates the GPU engine was issued a memory access that fell outside
      the valid VRAM aperture — either due to an incorrect address
      calculation in the ggml HIP backend, or a WSL2 dxgk translation bug.

   c) WSL2 Host-Side Ioctl Failures (dmesg_after_1.log:685–690)
      Six consecutive dxgkio_escape ioctl failures with error -75
      (EREMOTEIO = remote I/O error) at timestamps ~1627s. These are the
      host-side WSL2 GPU passthrough layer responses to the hung GPU —
      the Windows host driver could no longer service GPU commands from
      the VM, returning EREMOTEIO for every escape ioctl attempt.

   d) User-Space Abort (dmesg_after_1.log:731–732 + bench_1.log:1078)
      At ~1987s, the llama-bench process received SIGABRT (signal 6),
      consistent with the ROCm runtime's abort-on-error path after the
      memory aperture violation. The backtrace shows the crash propagated
      through ggml_backend_cuda_buffer_clear → hipStreamSynchronize →
      ggml_abort → llama_kv_cache constructor.

   Root Cause Summary:
   Batch 63 of ROCm for gfx1151 contains a regression in either:
     (A) The HSA runtime's memory address translation for large KV cache
         allocations on WSL2 via the dxgk layer, or
     (B) The ggml HIP backend's address calculation for the Qwen1.5-7B
         q5_k_m model's 32-layer KV cache (~1 GiB), which triggers an
         out-of-bounds GPU memory access on this specific hardware.
   The FaultMonitorThread in librocdxg correctly detected and reported the
   hang, but the underlying issue is a gfx1151-specific ROCm WSL2 regression
   in batch 63.

4. 下一步建议 (Next Steps)

   1. Bisect ROCm batches: Compare batch 63 (deb 63_20261010-010731,
      librocdxg.so 531 KB, libhsa-runtime64.so 5.3 MB) against the known-good
      baseline batch 61 (deb 61_20261009-233736, librocdxg.so 442 KB) —
      already noted in run.log as a working reference. Run the same
      llama-bench command on batch 61 to confirm it passes.

   2. File upstream bug with ROCm team: Submit to
      https://github.com/ROCm/ROCm/issues with the full bench_1.log,
      dmesg_after_1.log, rocminfo.log, and reproduction steps. Tag with
      "gfx1151", "WSL2", and "memory_aperture_violation".

   3. Check llama.cpp upstream: The crash occurs in ggml HIP backend during
      llama_kv_cache construction for Qwen1.5-7B (q5_k_m, 32 layers).
      Verify whether llama.cpp commit f2cc728 has any known gfx1151 issues
      at https://github.com/ggml-org/llama.cpp/issues and test with the
      latest main branch.

   4. Test with smaller model / fewer KV layers: Reduce the benchmark to a
      smaller model (e.g., Qwen1.5-1.5B) or reduce context length to
      determine if the fault is triggered specifically by large KV cache
      allocations (>1 GiB), which would narrow the scope to memory
      address translation in the WSL2 dxgk path.

================================================================================
End of report
================================================================================
