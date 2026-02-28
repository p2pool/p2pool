import os
import platform

_scale = {'kB': 1024, 'mB': 1024*1024,
    'KB': 1024, 'MB': 1024*1024}

def resident():
    if platform.system() == 'Windows':
        from wmi import WMI
        w = WMI('.')
        result = w.query("SELECT WorkingSet FROM Win32_PerfRawData_PerfProc_Process WHERE IDProcess=%d" % os.getpid())
        return int(result[0].WorkingSet)
    else:
        with open('/proc/%d/status' % os.getpid()) as f:
            v = f.read()
        i = v.index('VmRSS:')
        v = v[i:].split(None, 3)
        #assert len(v) == 3, v
        return float(v[1]) * _scale[v[2]]
