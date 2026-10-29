"""Time square GEMMs on CUDA for each tensor-core accumulate mode.

@module kachow.bench.gemm
@description Measure best-of-N TFLOPS for fp16_acc16, fp16_acc32, bf16_acc32 and tf32
with torch; the torch module is passed in, so the timing loop runs against a fake in
tests and against real CUDA from `kachow bench`.
@input torch module, int size, int iters, int rounds
@output dict[str, float] - best TFLOPS per case
@dependencies torch >= 2.7 (passed in), time (stdlib)

@example
    import torch; measure(torch, 8192, 50, 3)
"""
import time

WARMUP = 10


def case_settings(torch):
    return {
        'fp16_acc16': dict(dtype=torch.float16, fp16_accumulate=True),
        'fp16_acc32': dict(dtype=torch.float16),
        'bf16_acc32': dict(dtype=torch.bfloat16),
        'tf32': dict(dtype=torch.float32, tf32=True),
    }


def check_torch(torch):
    if not hasattr(torch.backends.cuda.matmul, 'allow_fp16_accumulation'):
        raise RuntimeError(f'torch {torch.__version__} lacks allow_fp16_accumulation (needs 2.7+)')


def tflops(torch, dtype, size, iters, fp16_accumulate=False, tf32=False):
    torch.backends.cuda.matmul.allow_fp16_accumulation = fp16_accumulate
    torch.backends.cuda.matmul.allow_tf32 = tf32
    a = torch.randn(size, size, device='cuda', dtype=dtype)
    b = torch.randn(size, size, device='cuda', dtype=dtype)
    for _ in range(WARMUP):
        a @ b
    torch.cuda.synchronize()
    start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    start.record()
    for _ in range(iters):
        a @ b
    end.record()
    torch.cuda.synchronize()
    seconds = start.elapsed_time(end) / 1000
    return 2 * size ** 3 * iters / seconds / 1e12


def measure(torch, size, iters, rounds, pause=1.0, sleep=time.sleep):
    check_torch(torch)
    cases = case_settings(torch)
    runs = {k: [] for k in cases}
    for _ in range(rounds):
        for name, kw in cases.items():
            runs[name].append(tflops(torch, size=size, iters=iters, **kw))
            sleep(pause)
    return {k: max(v) for k, v in runs.items()}
