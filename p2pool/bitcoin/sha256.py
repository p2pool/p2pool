from __future__ import division

import ctypes
import struct


k = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]

def process(state, chunk):
    def rightrotate(x, n):
        return (x >> n) | (x << 32 - n) % 2**32
    
    w = list(struct.unpack('>16I', chunk))
    for i in xrange(16, 64):
        s0 = rightrotate(w[i-15], 7) ^ rightrotate(w[i-15], 18) ^ (w[i-15] >> 3)
        s1 = rightrotate(w[i-2], 17) ^ rightrotate(w[i-2], 19) ^ (w[i-2] >> 10)
        w.append((w[i-16] + s0 + w[i-7] + s1) % 2**32)
    
    a, b, c, d, e, f, g, h = start_state = struct.unpack('>8I', state)
    for k_i, w_i in zip(k, w):
        t1 = (h + (rightrotate(e, 6) ^ rightrotate(e, 11) ^ rightrotate(e, 25)) + ((e & f) ^ (~e & g)) + k_i + w_i) % 2**32
        
        a, b, c, d, e, f, g, h = (
            (t1 + (rightrotate(a, 2) ^ rightrotate(a, 13) ^ rightrotate(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) % 2**32,
            a, b, c, (d + t1) % 2**32, e, f, g,
        )
    
    return struct.pack('>8I', *((x + y) % 2**32 for x, y in zip(start_state, [a, b, c, d, e, f, g, h])))

def make_accelerated_process_func():
    sha256_kernel = '4157415641554154555341504531c0420fb60407460fb64c0701c1e01841c1e1104409c8460fb64c07034409c8460fb64c070241c1e1084409c842894404c84983c0044983f82075c631c08b7c04c8897c04e84883c0044883f82075ee31ff0fb6043e440fb6443e01c1e01841c1e0104409c0440fb6443e034409c0440fb6443e0241c1e0084409c089443c884883c7044883ff4075c831c0bd07000000bb0400000041bb0600000041ba05000000e99c00000083fe0f0f868d0000008d78ff4989f44183e40f83e70f448b74bc888d78f283e80683e00f448b4c848883e70f46034ca4884589f54489f0448b44bc884d89efc1e00f41c1e60d49c1ef114409f84d89ef49c1ed0a49c1ef134489c74509fe4431f04431e84989fd4101c14489c049c1ed07c1e01941c1e00e4409e84989fd48c1ef0349c1ed124509e84431c031f84401c8428944a4884883c20489f089de4189e929c64129c183e6074183e1078b7cb4e84489de29c683e607448b6cb4e84889c64189fc83e60f4189fe448b44b4884489d644030229c64603448ce841c1e61a83e6078b74b4e84431ee21fe4431ee4d89e54101f089fe49c1ed0bc1e615c1e7074409ee4d89e549c1ec1949c1ed064409e74509ee4431f631fe458d2c3089c6f7de83e6078b7cb4e8be0100000029c683e6074189fc448b74b4e889fe4d89e0c1e6134d89e749c1e80d4409c64189f849c1ef0241c1e01e4509f84431c64d89e04189fc49c1e81641c1e40a4509c44589f04431e641bc020000004109f84129c44421f74183e407462344a4e84109f8bf0300000029c74401c683e70744016cbce84101f58d700146896c8ce883fe400f854afeffff31c08b5404e8035404c889d688540103c1ee184088340189d6c1ee10408874010189d6c1ee0840887401024883c0044883f82075cd585b5d415c415d415e415fc3909090909090909090'.decode('hex') # does this look suspicious?

    libc = ctypes.CDLL("libc.so.6")
    libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    libc.sysconf.restype = ctypes.c_long
    def make_executable(addr, size):
        _SC_PAGESIZE = 30
        PROT_READ = 1
        PROT_WRITE = 2
        PROT_EXECUTE = 4
        pagesize = libc.sysconf(_SC_PAGESIZE)
        if pagesize <= 0:
            raise Error()
        gap = addr % pagesize
        if libc.mprotect(addr - gap, size + gap, PROT_READ | PROT_WRITE | PROT_EXECUTE):
            raise Error()
    
    sha256_func = ctypes.cast(sha256_kernel, ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_char_p))
    make_executable(ctypes.cast(sha256_kernel, ctypes.c_void_p).value, len(sha256_kernel))
    
    k2 = (ctypes.c_uint32*len(k))(*k)
    def process(state, chunk):
        s = ctypes.create_string_buffer(32)
        sha256_func(state, chunk, k2, s)
        return s.raw
        sha256_kernel # keeps it from being freed
    return process
process = make_accelerated_process_func()

initial_state = struct.pack('>8I', 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19)

class sha256(object):
    digest_size = 256//8
    block_size = 512//8
    
    def __init__(self, data='', _=(initial_state, '', 0)):
        self.state, self.buf, self.length = _
        self.update(data)
    
    def update(self, data):
        state = self.state
        buf = self.buf + data
        
        chunks = [buf[i:i + self.block_size] for i in xrange(0, len(buf) + 1, self.block_size)]
        for chunk in chunks[:-1]:
            state = process(state, chunk)
        
        self.state = state
        self.buf = chunks[-1]
        
        self.length += 8*len(data)
    
    def copy(self, data=''):
        return self.__class__(data, (self.state, self.buf, self.length))
    
    def digest(self):
        state = self.state
        buf = self.buf + '\x80' + '\x00'*((self.block_size - 9 - len(self.buf)) % self.block_size) + struct.pack('>Q', self.length)
        
        for chunk in [buf[i:i + self.block_size] for i in xrange(0, len(buf), self.block_size)]:
            state = process(state, chunk)
        
        return state
    
    def hexdigest(self):
        return self.digest().encode('hex')
