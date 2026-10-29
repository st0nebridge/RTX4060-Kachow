"""Unit tests for kachow.bench (verdict and the GEMM timing loop on a fake torch)."""
import pytest

from faketorch import fake_torch
from kachow.bench import gemm, verdict

# Hardware results, 2026-10-28 (RTX 4060 Laptop, 8192^3 x 50, best of 3)
LOCKED = {'fp16_acc16': 49.1, 'fp16_acc32': 29.6, 'bf16_acc32': 30.2, 'tf32': 14.7}
UNLOCKED = {'fp16_acc16': 45.75, 'fp16_acc32': 45.52, 'bf16_acc32': 46.88, 'tf32': 22.64}


def test_recorded_results_get_the_right_verdict():
    assert verdict.verdict(LOCKED) == 'LOCKED (half rate)'
    assert verdict.verdict(UNLOCKED) == 'UNLOCKED'


def test_threshold_is_exclusive():
    best = {'fp16_acc16': 10.0, 'fp16_acc32': 8.0}
    assert verdict.verdict(best) == 'LOCKED (half rate)'
    assert verdict.verdict({**best, 'fp16_acc32': 8.01}) == 'UNLOCKED'


def test_ratios_are_relative_to_fp16_acc16():
    r = verdict.ratios(LOCKED)
    assert r['fp16_acc16'] == 1.0
    assert round(r['fp16_acc32'], 2) == 0.60 and round(r['tf32'], 2) == 0.30
    assert list(verdict.ratios({'fp16_acc16': 2.0, 'tf32': 1.0})) == ['fp16_acc16', 'tf32']


def test_ratios_reject_zero_reference():
    with pytest.raises(ValueError):
        verdict.ratios({'fp16_acc16': 0.0, 'fp16_acc32': 1.0})


def test_report_matches_recorded_output_format():
    # rounded inputs: 45.52 / 45.75 prints 0.99 where the unrounded run printed 1.00
    text = verdict.report('NVIDIA GeForce RTX 4060 Laptop GPU', '2.11.0+cu128', 8192, 50, 3, UNLOCKED)
    assert text.splitlines() == [
        'NVIDIA GeForce RTX 4060 Laptop GPU  torch 2.11.0+cu128  8192^3 x 50, best of 3',
        '  fp16_acc16     45.8 TFLOPS   ratio to fp16_acc16 = 1.00',
        '  fp16_acc32     45.5 TFLOPS   ratio to fp16_acc16 = 0.99',
        '  bf16_acc32     46.9 TFLOPS   ratio to fp16_acc16 = 1.02',
        '  tf32           22.6 TFLOPS   ratio to fp16_acc16 = 0.49',
        'FP32-accumulate tensor rate: UNLOCKED',
        '{"fp16_acc16": 45.75, "fp16_acc32": 45.52, "bf16_acc32": 46.88, "tf32": 22.64}',
    ]


def test_tflops_times_only_the_measured_iterations():
    t = fake_torch(cost=0.5)
    v = gemm.tflops(t, 'f16', size=1000, iters=4, fp16_accumulate=True)
    assert t.matmuls == gemm.WARMUP + 4 and t.syncs == 2
    assert v == pytest.approx(2 * 1000 ** 3 * 4 / 2.0 / 1e12)
    assert t.backends.cuda.matmul.allow_fp16_accumulation is True


def test_tflops_sets_tf32_flag():
    t = fake_torch()
    gemm.tflops(t, 'f32', size=8, iters=1, tf32=True)
    assert t.backends.cuda.matmul.allow_tf32 is True and t.backends.cuda.matmul.allow_fp16_accumulation is False


def test_measure_keeps_the_best_round_and_shows_half_rate():
    t = fake_torch()
    pauses = []
    best = gemm.measure(t, size=100, iters=2, rounds=2, pause=0.25, sleep=pauses.append)
    assert list(best) == list(verdict.CASES)
    assert pauses == [0.25] * 8
    assert verdict.verdict(best) == 'LOCKED (half rate)'
    assert best['fp16_acc16'] == pytest.approx(2 * best['fp16_acc32'])


def test_measure_refuses_old_torch():
    with pytest.raises(RuntimeError, match='needs 2.7'):
        gemm.measure(fake_torch(has_fp16_acc=False), 8, 1, 1, sleep=lambda s: None)


def test_ratios_reject_negative_reference():
    with pytest.raises(ValueError):
        verdict.ratios({'fp16_acc16': -1.0, 'fp16_acc32': 1.0})


def test_report_rounds_the_json_line_to_two_places():
    text = verdict.report('GPU', 'v', 8, 1, 1, {'fp16_acc16': 45.756, 'fp16_acc32': 45.0})
    assert text.splitlines()[-1] == '{"fp16_acc16": 45.76, "fp16_acc32": 45.0}'


def test_case_settings_pick_dtype_and_flags_per_case():
    t = fake_torch()
    assert gemm.case_settings(t) == {
        'fp16_acc16': {'dtype': 'f16', 'fp16_accumulate': True},
        'fp16_acc32': {'dtype': 'f16'},
        'bf16_acc32': {'dtype': 'bf16'},
        'tf32': {'dtype': 'f32', 'tf32': True},
    }


def test_tflops_warms_up_ten_times_and_resets_both_flags():
    t = fake_torch()
    t.backends.cuda.matmul.allow_tf32 = t.backends.cuda.matmul.allow_fp16_accumulation = True
    gemm.tflops(t, 'f16', size=8, iters=3)
    assert t.matmuls == 10 + 3
    assert t.backends.cuda.matmul.allow_tf32 is False and t.backends.cuda.matmul.allow_fp16_accumulation is False


def test_tflops_uses_true_division_throughout():
    # 4 x 3/32 s = 0.375 s exactly: 8e9 / 0.375 is not a whole number, so // would differ
    t = fake_torch(cost=3 / 32)
    v = gemm.tflops(t, 'f16', size=1000, iters=4, fp16_accumulate=True)
    assert v == 2 * 1000 ** 3 * 4 / 0.375 / 1e12


def test_measure_pauses_one_second_between_cases_by_default():
    pauses = []
    gemm.measure(fake_torch(), 8, 1, 1, sleep=pauses.append)
    assert pauses == [1.0] * 4
