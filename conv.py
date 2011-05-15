import struct

from twisted.internet import defer

import sha256

def bits_to_target(bits):
    return (bits & 0x00ffffff) * 2 ** (8 * ((bits >> 24) - 3))

def reverse_chunks(s, l):
    return ''.join(reversed([s[x:x+l] for x in xrange(0, len(s), l)]))

class BlockAttempt(object):
    def __init__(self, version, prev_block, merkle_root, timestamp, bits):
        self.version, self.prev_block, self.merkle_root, self.timestamp, self.bits = version, prev_block, merkle_root, timestamp, bits
    
    def getwork(self, target_multiplier=1):
        target = bits_to_target(self.bits) * target_multiplier
        
        prev_block2 = reverse_chunks('%064x' % self.prev_block, 8).decode('hex')
        merkle_root2 = reverse_chunks('%064x' % self.merkle_root, 8).decode('hex')
        data = struct.pack(">I32s32sIII", self.version, prev_block2, merkle_root2, self.timestamp, self.bits, 0).encode('hex') + "000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000"
        
        prev_block3 = ('%064x' % self.prev_block).decode('hex')[::-1]
        merkle_root3 = ('%064x' % self.merkle_root).decode('hex')[::-1]
        data2 = struct.pack("<I32s32s", self.version, prev_block3, merkle_root3)
        
        return {
            "data": data,
            "hash1": "00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000",
            "target": ('%064x' % (target,)).decode('hex')[::-1].encode('hex'),
            "midstate": reverse_chunks(sha256.process(data2[:64])[::-1], 4).encode('hex'),
        }
    
    @classmethod
    def from_getwork(cls, getwork):
        version, prev_block, merkle_root, timestamp, bits, nonce = struct.unpack(">I32s32sIII", getwork['data'][:160].decode('hex'))
        prev_block = int(reverse_chunks(prev_block.encode('hex'), 8), 16)
        merkle_root = int(reverse_chunks(merkle_root.encode('hex'), 8), 16)
        
        ba = cls(version, prev_block, merkle_root, timestamp, bits)
        
        getwork2 = ba.getwork()
        if getwork2 != getwork:
            print ba.__dict__
            for k in getwork:
                print k
                print getwork[k]
                print getwork2[k]
                print getwork[k] == getwork2[k]
                print
            raise ValueError("nonsensical getwork request response")
        
        return ba
