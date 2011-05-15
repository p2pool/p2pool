from __future__ import division

import struct

initial_state = struct.pack('>8I', 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19)
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

def process(chunk, state=initial_state):
    def rightrotate(x, n):
        return (x >> n) | (x << 32 - n) % 2**32
    
    assert len(chunk) == 512//8
    w = list(struct.unpack('>16I', chunk))
    
    assert len(state) == 256//8
    state = struct.unpack('>8I', state)
    
    for i in xrange(16, 64):
        s0 = rightrotate(w[i-15], 7) ^ rightrotate(w[i-15], 18) ^ (w[i-15] >> 3)
        s1 = rightrotate(w[i-2], 17) ^ rightrotate(w[i-2], 19) ^ (w[i-2] >> 10)
        w.append((w[i-16] + s0 + w[i-7] + s1) % 2**32)
    
    a, b, c, d, e, f, g, h = state
    
    for i in xrange(64):
        s0 = rightrotate(a, 2) ^ rightrotate(a, 13) ^ rightrotate(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        t2 = (s0 + maj) % 2**32
        s1 = rightrotate(e, 6) ^ rightrotate(e, 11) ^ rightrotate(e, 25)
        ch = (e & f) ^ (~e & g)
        t1 = (h + s1 + ch + k[i] + w[i]) % 2**32

        h = g
        g = f
        f = e
        e = (d + t1) % 2**32
        d = c
        c = b
        b = a
        a = (t1 + t2) % 2**32
    
    state = [(x + y) % 2**32 for x, y in zip(state, [a, b, c, d, e, f, g, h])]
    
    return struct.pack('>8I', *state)

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
            state = process(chunk, state)
        
        self.state = state
        self.buf = chunks[-1]
        
        self.length += 8*len(data)
    
    def copy(self, data=''):
        return self.__class__(data, (self.state, self.buf, self.length))
    
    def digest(self):
        state = self.state
        buf = self.buf + '\x80' + '\x00'*((self.block_size - 9 - len(self.buf)) % self.block_size) + struct.pack('>Q', self.length)
        
        for chunk in [buf[i:i + self.block_size] for i in xrange(0, len(buf), self.block_size)]:
            state = process(chunk, state)
        
        return state
    
    def hexdigest(self):
        return self.digest().encode('hex')

if __name__ == '__main__':
    import hashlib
    import random
    for test in ['', 'a', 'b', 'abc', 'abc'*50, 'hello world']:
        print test
        print sha256(test).hexdigest()
        print hashlib.sha256(test).hexdigest()
        print
    def random_str(l):
        return ''.join(chr(random.randrange(256)) for i in xrange(l))
    for length in xrange(1500):
        test = random_str(length)
        a = sha256(test).hexdigest()
        b = hashlib.sha256(test).hexdigest()
        print length, a, b
        if a != b:
            print 'ERROR!'
            raise ValueError()
    while True:
        test = random_str(int(random.expovariate(1/1000)))
        test2 = random_str(int(random.expovariate(1/1000)))
        
        a = sha256(test)
        a = a.copy()
        a.update(test2)
        a = a.hexdigest()
        
        b = hashlib.sha256(test)
        b = b.copy()
        b.update(test2)
        b = b.hexdigest()
        print a, b
        if a != b:
            print 'ERROR!'
            raise ValueError()
