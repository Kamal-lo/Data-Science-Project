"""Windows Job Objects and Linux cgroup v2 with a supervised OCR process group."""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import signal
import sys
from time import monotonic


def memory_sample(stage, **details):
    """Measured process private bytes and RSS, not a prediction of model needs."""
    import psutil
    process = psutil.Process()
    memory, system = process.memory_info(), psutil.virtual_memory()
    return dict(stage=stage, monotonic_seconds=monotonic(), pid=process.pid,
                rss_bytes=memory.rss, private_bytes=getattr(memory, 'private', None),
                available_physical_bytes=system.available, total_physical_bytes=system.total, **details)


class ResourceProtectionError(RuntimeError):
    pass


def container_memory_limit():
    """Read the effective ceiling of a private Docker cgroup v2 namespace."""
    try:
        if '0::/' not in Path('/proc/self/cgroup').read_text().splitlines():
            raise ValueError('private cgroup namespace required')
        limit = int(Path('/sys/fs/cgroup/memory.max').read_text())
        if limit <= 0:
            raise ValueError('invalid limit')
        return limit
    except (OSError, ValueError) as exc:
        raise ResourceProtectionError('P2 OCR requires a finite Docker --memory limit and --cgroupns=private on cgroup v2.') from exc


def conversion_process_bytes(process):
    # PSS counts shared native libraries proportionally across Linux workers.
    return process.memory_full_info().pss if sys.platform == 'linux' else process.memory_info().rss


class LinuxContainerGuard:
    """Kernel ceiling for the container; sampled PSS budget for the OCR tree."""
    def __init__(self, limit):
        self.container_limit = container_memory_limit()
        self.limit = limit
        self.process = None
        self.peak = 0
        self.hit = False
        self.events = Path('/sys/fs/cgroup/memory.events')
        self.initial_oom = self._oom_kills()

    def _oom_kills(self):
        return int(dict(line.split() for line in self.events.read_text().splitlines())['oom_kill'])

    def snapshot(self):
        import psutil
        total = 0
        try:
            root = psutil.Process(self.process.pid)
            for member in [root, *root.children(recursive=True)]:
                try:
                    total += conversion_process_bytes(member)
                except psutil.NoSuchProcess:
                    continue
        except psutil.NoSuchProcess:
            pass
        self.peak = max(self.peak, total)
        self.hit |= total > self.limit
        return dict(mechanism='linux_cgroup_v2_and_process_group', memory_metric='sampled_tree_pss_bytes',
                    limit_bytes=self.limit, container_limit_bytes=self.container_limit,
                    peak_sampled_pss_bytes=self.peak, container_oom_kills=self._oom_kills()-self.initial_oom,
                    memory_limit_hit=self.hit)

    def terminate(self):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def __enter__(self): return self
    def __exit__(self, *args): self.terminate()


class _Basic(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', w.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', w.DWORD), ('Affinity', ctypes.c_size_t),
                ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]


class _IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _Extended(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _Basic), ('IoInfo', _IO),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class _Port(ctypes.Structure):
    _fields_ = [('CompletionKey', ctypes.c_void_p), ('CompletionPort', w.HANDLE)]


def _kernel():
    if os.name != 'nt':
        raise ResourceProtectionError('Strict OCR memory protection requires Windows Job Objects.')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
        'OpenJobObjectW': ([w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'GetCurrentProcess': ([], w.HANDLE),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
        'CreateIoCompletionPort': ([w.HANDLE, w.HANDLE, ctypes.c_size_t, w.DWORD], w.HANDLE),
        'GetQueuedCompletionStatus': ([w.HANDLE, ctypes.POINTER(w.DWORD), ctypes.POINTER(ctypes.c_size_t),
                                       ctypes.POINTER(ctypes.c_void_p), w.DWORD], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(k, name); fn.argtypes = args; fn.restype = result
    return k


def _check(ok):
    if not ok:
        raise ResourceProtectionError(str(ctypes.WinError(ctypes.get_last_error())))
    return ok


class WindowsJob:
    """Parent-owned named job; worker joins before importing inference libraries."""
    def __init__(self, name, memory_bytes):
        if type(memory_bytes) is not int or memory_bytes < 1:
            raise ValueError('max_worker_memory_bytes must be a positive integer.')
        self.k = _kernel(); self.handle = self.port = None
        self.memory_bytes, self.name = memory_bytes, name
        self.memory_limit_hit = False
        try:
            self.handle = _check(self.k.CreateJobObjectW(None, name))
            info = _Extended()
            # JOB_MEMORY + KILL_ON_JOB_CLOSE; no BREAKAWAY flags.
            info.BasicLimitInformation.LimitFlags = 0x200 | 0x2000
            info.JobMemoryLimit = memory_bytes
            _check(self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)))
            self.port = _check(self.k.CreateIoCompletionPort(w.HANDLE(-1), None, 0, 1))
            port = _Port(1, self.port)
            _check(self.k.SetInformationJobObject(self.handle, 7, ctypes.byref(port), ctypes.sizeof(port)))
        except BaseException:
            self.close(); raise

    def snapshot(self):
        while True:
            message, key, process = w.DWORD(), ctypes.c_size_t(), ctypes.c_void_p()
            ok = self.k.GetQueuedCompletionStatus(self.port, ctypes.byref(message), ctypes.byref(key),
                                                   ctypes.byref(process), 0)
            if not ok:
                if ctypes.get_last_error() == 258: break  # WAIT_TIMEOUT
                _check(ok)
            if message.value == 10: self.memory_limit_hit = True  # JOB_MEMORY_LIMIT
        info = _Extended()
        _check(self.k.QueryInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info), None))
        return {'mechanism': 'windows_job_object', 'memory_metric': 'job_private_commit_bytes',
                'limit_bytes': self.memory_bytes, 'peak_job_memory_bytes': info.PeakJobMemoryUsed,
                'peak_counter_may_include_rejected_charge': True,
                'memory_limit_hit': self.memory_limit_hit, 'children_covered': True,
                'kill_on_job_close': True, 'breakaway_allowed': False}

    def terminate(self):
        _check(self.k.TerminateJobObject(self.handle, 1))

    def close(self):
        # Closing the parent's last job handle also kills remaining descendants.
        if self.handle: self.k.CloseHandle(self.handle); self.handle = None
        if self.port: self.k.CloseHandle(self.port); self.port = None

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def join_job(name):
    """Fail closed. No model initialization until the kernel accepts membership."""
    k = _kernel()
    handle = _check(k.OpenJobObjectW(0x1, False, name))  # ASSIGN_PROCESS
    try:
        _check(k.AssignProcessToJobObject(handle, k.GetCurrentProcess()))
    finally:
        k.CloseHandle(handle)
