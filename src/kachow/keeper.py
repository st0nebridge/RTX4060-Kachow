"""Keep the RTX powered: hold a CUDA context and use it every second.

@module kachow.keeper
@description In hybrid (Optimus) mode the NVIDIA driver powers the idle RTX off, and the
power-off resets the unlock. A process that keeps using the GPU is never idled. hold()
opens a context through the CUDA driver API (nvcuda.dll, which every NVIDIA driver ships;
no toolkit, no torch) and writes 1 MiB every `period` seconds until `stop(rounds)` is true.
@input a CUDA driver library (load(), or a fake), a log callback
@output rounds held when stop() ends it; KeeperError when a CUDA call fails
@dependencies ctypes, time (stdlib)

@example
    keeper.hold(keeper.load(), print)   # holds until the process is stopped
"""
import ctypes
import time

SIZE = 1 << 20
SIGNATURES = {
    'cuInit': [ctypes.c_uint],
    'cuDeviceGet': [ctypes.POINTER(ctypes.c_int), ctypes.c_int],
    'cuDeviceGetName': [ctypes.c_char_p, ctypes.c_int, ctypes.c_int],
    'cuCtxCreate_v2': [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_int],
    'cuMemAlloc_v2': [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t],
    'cuMemsetD8_v2': [ctypes.c_uint64, ctypes.c_ubyte, ctypes.c_size_t],
    'cuCtxSynchronize': [],
}


class KeeperError(RuntimeError):
    pass


def bind(cu):
    for name, sig in SIGNATURES.items():
        getattr(cu, name).argtypes = sig
    return cu


def load():  # pragma: no cover - needs the NVIDIA driver; tests pass a fake
    return bind(ctypes.WinDLL('nvcuda.dll'))


def _call(cu, name, *args):
    result = getattr(cu, name)(*args)
    if result:
        raise KeeperError(f'{name} failed: CUresult {result}')


def hold(cu, say, period=1.0, sleep=time.sleep, stop=lambda rounds: False, clock=time.monotonic):
    t0 = clock()
    _call(cu, 'cuInit', 0)
    dev = ctypes.c_int()
    _call(cu, 'cuDeviceGet', ctypes.byref(dev), 0)
    name = ctypes.create_string_buffer(128)
    _call(cu, 'cuDeviceGetName', name, 128, dev)
    ctx = ctypes.c_void_p()
    _call(cu, 'cuCtxCreate_v2', ctypes.byref(ctx), 0, dev)
    ptr = ctypes.c_uint64()
    _call(cu, 'cuMemAlloc_v2', ctypes.byref(ptr), SIZE)
    say(f'holding {name.value.decode(errors="replace")} (context up in {clock() - t0:.2f} s)')
    rounds = 0
    while True:
        _call(cu, 'cuMemsetD8_v2', ptr, rounds & 0xFF, SIZE)
        _call(cu, 'cuCtxSynchronize')
        rounds += 1
        if rounds == 60 or not rounds % 3600:
            say(f'alive {rounds} s')
        if stop(rounds):
            return rounds
        sleep(period)
