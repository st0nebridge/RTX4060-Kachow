"""Test helper: a stand-in torch module for the GEMM timing loop.

@module tests.faketorch
@description A fake torch whose matmuls advance a virtual clock: half rate for FP32
accumulate when `locked`, so gemm.measure and `kachow bench` run without a GPU.
@dependencies types (stdlib)
"""
from types import SimpleNamespace


class FakeEvent:
    def __init__(self, clock, enable_timing):
        assert enable_timing
        self.clock, self.t = clock, None

    def record(self):
        self.t = self.clock.now

    def elapsed_time(self, other):
        return (other.t - self.t) * 1000.0


class FakeTensor:
    def __init__(self, torch, dtype):
        self.torch, self.dtype = torch, dtype

    def __matmul__(self, other):
        m = self.torch.backends.cuda.matmul
        half = self.torch.locked and (self.dtype != 'f16' or not m.allow_fp16_accumulation)
        self.torch.clock.now += self.torch.cost * (2 if half else 1)
        self.torch.matmuls += 1
        return self


def fake_torch(has_fp16_acc=True, cost=0.01, locked=True):
    matmul = SimpleNamespace(allow_tf32=False)
    if has_fp16_acc:
        matmul.allow_fp16_accumulation = False
    t = SimpleNamespace(float16='f16', bfloat16='bf16', float32='f32', __version__='fake',
                        backends=SimpleNamespace(cuda=SimpleNamespace(matmul=matmul)),
                        clock=SimpleNamespace(now=0.0), cost=cost, locked=locked, matmuls=0, syncs=0)
    t.randn = lambda *shape, device, dtype: FakeTensor(t, dtype)

    def sync():
        t.syncs += 1
    t.cuda = SimpleNamespace(synchronize=sync, Event=lambda enable_timing: FakeEvent(t.clock, enable_timing),
                             get_device_name=lambda i: f'Fake GPU {i}')
    return t
