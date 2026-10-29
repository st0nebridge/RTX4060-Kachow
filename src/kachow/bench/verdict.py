"""Judge benchmark results: ratios to FP16-accumulate and the locked/unlocked verdict.

@module kachow.bench.verdict
@description Turn best-of-N TFLOPS per case into ratios against fp16_acc16 and a verdict;
pure, so it is testable without a GPU.
@input dict[str, float] - best TFLOPS per case name
@output str report lines; verdict string
@dependencies json (stdlib)

@example
    verdict({"fp16_acc16": 45.7, "fp16_acc32": 45.5, ...})   # 'UNLOCKED'
"""
import json

CASES = ('fp16_acc16', 'fp16_acc32', 'bf16_acc32', 'tf32')
REFERENCE = 'fp16_acc16'
UNLOCKED_THRESHOLD = 0.8


def ratios(best):
    ref = best[REFERENCE]
    if ref <= 0:
        raise ValueError('reference case measured no throughput')
    return {name: best[name] / ref for name in CASES if name in best}


def is_unlocked(best, threshold=UNLOCKED_THRESHOLD):
    return ratios(best)['fp16_acc32'] > threshold


def verdict(best, threshold=UNLOCKED_THRESHOLD):
    return 'UNLOCKED' if is_unlocked(best, threshold) else 'LOCKED (half rate)'


def report(device, torch_version, size, iters, rounds, best):
    r = ratios(best)
    lines = [f'{device}  torch {torch_version}  {size}^3 x {iters}, best of {rounds}']
    lines += [f'  {name:11s} {best[name]:7.1f} TFLOPS   ratio to {REFERENCE} = {r[name]:.2f}' for name in r]
    lines.append(f'FP32-accumulate tensor rate: {verdict(best)}')
    lines.append(json.dumps({k: round(v, 2) for k, v in best.items()}))
    return '\n'.join(lines)
