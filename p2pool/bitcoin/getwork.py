'''
Representation of a getwork request/reply
'''

from __future__ import division

import struct

from . import data as bitcoin_data
from . import sha256

def _reverse_chunks(s, l):
    return ''.join(reversed([s[x:x+l] for x in xrange(0, len(s), l)]))

def _swap(s, l):
    return ''.join(s[x:x+l][::-1] for x in xrange(0, len(s), l))

class BlockAttempt(object):
    def __init__(self, version, previous_block, merkle_root, timestamp, target):
        assert version == 1
        self.version, self.previous_block, self.merkle_root, self.timestamp, self.target = version, previous_block, merkle_root, timestamp, target
    
    def __hash__(self):
        return hash((self.version, self.previous_block, self.merkle_root, self.timestamp, self.target))
    
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
    
    def getwork(self, target=None, _check=3):
        target2 = self.target if target is None else target
        if target2 >= 2**256//2**32:
            raise ValueError("target higher than standard maximum")
        
        block_data = bitcoin_data.block_header_type.pack(dict(
            version=self.version,
            previous_block=self.previous_block,
            merkle_root=self.merkle_root,
            timestamp=self.timestamp,
            target=self.target,
            nonce=0,
        ))
        
        getwork = {
            'data': _swap(block_data, 4).encode('hex') + '000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000',
            'hash1': '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
            'target': ('%064x' % (target2,)).decode('hex')[::-1].encode('hex'),
            'midstate': _reverse_chunks(sha256.process(block_data[:64])[::-1], 4).encode('hex'),
        }
        
        if _check:
            self2 = self.__class__.from_getwork(getwork, _check=_check - 1, _check_target=target)
            if self2 != self:
                raise ValueError('failed check - input invalid or implementation error')
        
        return getwork
    
    @classmethod
    def from_getwork(cls, getwork, _check=3, _check_target=None):
        attrs = decode_data(getwork['data'])
        attrs.pop('nonce')
        
        ba = cls(**attrs)
        
        if _check:
            getwork2 = ba.getwork(_check_target, _check=_check - 1)
            if getwork2 != getwork:
                raise ValueError('failed check - input invalid or implementation error')
        
        return ba

def decode_data(data):
    return bitcoin_data.block_header_type.unpack(_swap(data.decode('hex'), 4)[:80])

if __name__ == '__main__':
    BlockAttempt.from_getwork({
        'target': '0000000000000000000000000000000000000000000000f2b944000000000000',
        'midstate': '5982f893102dec03e374b472647c4f19b1b6d21ae4b2ac624f3d2f41b9719404',
        'hash1': '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
        'data': '0000000163930d52a5ffca79b29b95a659a302cd4e1654194780499000002274000000002e133d9e51f45bc0886d05252038e421e82bff18b67dc14b90d9c3c2f422cd5c4dd4598e1a44b9f200000000000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000'
}, _check=100)
    BlockAttempt.from_getwork({
        "midstate" : "f4a9b048c0cb9791bc94b13ee0eec21e713963d524fd140b58bb754dd7b0955f",
        "data" : "000000019a1d7342fb62090bda686b22d90f9f73d0f5c418b9c980cd0000011a00000000680b07c8a2f97ecd831f951806857e09f98a3b81cdef1fa71982934fef8dc3444e18585d1a0abbcf00000000000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000",
        "hash1" : "00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000",
        "target" : "0000000000000000000000000000000000000000000000cfbb0a000000000000"
    })
    ba = BlockAttempt(
        1,
        0x148135e10208db85abb62754341a392eab1f186aab077a831cf7,
        0x534ea08be1ab529f484369344b6d5423ef5a0767db9b3ebb4e182bbb67962520,
        1305759879,
        0x44b9f20000000000000000000000000000000000000000000000,
    )
    ba.getwork(2**192*5, 100)
    ba.getwork(1, 100)
    ba.getwork(10, 100)
    ba.getwork()
    ba.getwork(_check=100)
