import os
import platform

_scale = {'kB': 1024, 'mB': 1024*1024,
    'KB': 1024, 'MB': 1024*1024}

def resident():
    """Return resident memory usage in bytes, or 0 if unavailable."""
    # Windows: use ctypes (no external wmi dependency needed)
    if platform.system() == 'Windows':
        try:
            import ctypes
            import ctypes.wintypes
            # GetProcessMemoryInfo via kernel32/psapi
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('cb', ctypes.wintypes.DWORD),
                    ('PageFaultCount', ctypes.wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                ]
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            psapi = ctypes.windll.psapi
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize
        except Exception:
            pass
        return 0
    # Linux: read /proc/<pid>/status
    try:
        with open('/proc/%d/status' % os.getpid()) as f:
            v = f.read()
        i = v.index('VmRSS:')
        v = v[i:].split(None, 3)
        return float(v[1]) * _scale[v[2]]
    except Exception:
        pass
    # macOS or other: try resource module
    try:
        import resource
        # ru_maxrss is in bytes on Linux, kilobytes on macOS
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        if platform.system() == 'Darwin':
            return rusage.ru_maxrss  # bytes on macOS
        return rusage.ru_maxrss * 1024  # KB on Linux
    except Exception:
        pass
    return 0
