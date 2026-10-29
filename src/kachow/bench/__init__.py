"""Tensor-core throughput benchmark: is FP32-accumulate running at half rate?

@module kachow.bench
@description Locked consumer cards run FP16/BF16 with FP32 accumulate (and TF32) at half
the FP16-accumulate rate; unlocked, the ratio is about 1.0. The ratio cancels clocks,
power limits and thermals. `gemm` times the cases on CUDA, `verdict` judges them, and
run() does both for `kachow bench`.
@input torch (with CUDA, or a fake), matrix size, iterations, rounds
@output (report text, True when unlocked)
@dependencies kachow.bench.gemm, kachow.bench.verdict
"""
from . import gemm, verdict


def run(torch, size, iters, rounds):
    best = gemm.measure(torch, size, iters, rounds)
    text = verdict.report(torch.cuda.get_device_name(0), torch.__version__, size, iters, rounds, best)
    return text, verdict.is_unlocked(best)
