'''
Representation of a getwork request/reply
'''

from __future__ import division

import struct

from . import data as bitcoin_data
from . import sha256

def _reverse_chunks(s, l):
    return ''.join(reversed([s[x:x+l] for x in xrange(0, len(s), l)]))

class BlockAttempt(object):
    def __init__(self, version, previous_block, merkle_root, timestamp, bits):
        self.version, self.previous_block, self.merkle_root, self.timestamp, self.bits = version, previous_block, merkle_root, timestamp, bits
    
    def __hash__(self):
        return hash((self.version, self.previous_block, self.merkle_root, self.timestamp, self.bits))
    
    def __repr__(self):
        return '<BlockAttempt %s>' % (' '.join('%s=%s' % (k, hex(v))) for k, v in self.__dict__.iteritems())
    
    def __eq__(self, other):
        if not isinstance(other, BlockAttempt):
            raise ValueError('comparisons only valid with other BlockAttempts')
        return self.__dict__ == other.__dict__
    
    def __ne__(self, other):
        return not (self == other)
    
    def __repr__(self):
        return 'BlockAttempt(%s)' % (', '.join('%s=%r' % (k, v) for k, v in self.__dict__.iteritems()),)
    
    def getwork(self, target_multiplier=1, _check=2):
        target = bitcoin_data.bits_to_target(self.bits) * target_multiplier
        if target >= 2**256//2**32:
            raise ValueError("target higher than standard maximum")
        
        previous_block2 = _reverse_chunks('%064x' % self.previous_block, 8).decode('hex')
        merkle_root2 = _reverse_chunks('%064x' % self.merkle_root, 8).decode('hex')
        data = struct.pack('>I32s32sIII', self.version, previous_block2, merkle_root2, self.timestamp, self.bits, 0).encode('hex') + '000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000'
        
        previous_block3 = ('%064x' % self.previous_block).decode('hex')[::-1]
        merkle_root3 = ('%064x' % self.merkle_root).decode('hex')[::-1]
        data2 = struct.pack('<I32s32s', self.version, previous_block3, merkle_root3)
        
        getwork = {
            'data': data,
            'hash1': '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
            'target': ('%064x' % (target,)).decode('hex')[::-1].encode('hex'),
            'midstate': _reverse_chunks(sha256.process(data2[:64])[::-1], 4).encode('hex'),
        }
        
        if _check:
            self2 = self.__class__.from_getwork(getwork, _check=_check - 1, _check_multiplier=target_multiplier)
            if self2 != self:
                raise ValueError('failed check - input invalid or implementation error')
        
        return getwork
    
    @classmethod
    def from_getwork(cls, getwork, _check=2, _check_multiplier=1):
        attrs = decode_data(getwork['data'])
        attrs.pop('nonce')
        
        ba = cls(**attrs)
        
        if _check:
            getwork2 = ba.getwork(_check_multiplier, _check=_check - 1)
            if getwork2 != getwork:
                raise ValueError('failed check - input invalid or implementation error')
        
        return ba

def decode_data(data):
    version, previous_block, merkle_root, timestamp, bits, nonce = struct.unpack('>I32s32sIII', data[:160].decode('hex'))
    previous_block = int(_reverse_chunks(previous_block.encode('hex'), 8), 16)
    merkle_root = int(_reverse_chunks(merkle_root.encode('hex'), 8), 16)
    return dict(version=version, previous_block=previous_block, merkle_root=merkle_root, timestamp=timestamp, bits=bits, nonce=nonce)

if __name__ == '__main__':
    ba = BlockAttempt(
        1,
        0x000000000000148135e10208db85abb62754341a392eab1f186aab077a831cf7,
        0x534ea08be1ab529f484369344b6d5423ef5a0767db9b3ebb4e182bbb67962520,
        1305759879,
        440711666,
    )
    ba.getwork(1, 100)
    ba.getwork(10, 100)
    ba.from_getwork({
        'target': '0000000000000000000000000000000000000000000000f2b944000000000000',
        'midstate': '5982f893102dec03e374b472647c4f19b1b6d21ae4b2ac624f3d2f41b9719404',
        'hash1': '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
        'data': '0000000163930d52a5ffca79b29b95a659a302cd4e1654194780499000002274000000002e133d9e51f45bc0886d05252038e421e82bff18b67dc14b90d9c3c2f422cd5c4dd4598e1a44b9f200000000000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000'
}, _check=100)
