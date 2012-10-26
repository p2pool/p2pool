'''
Representation of a getwork request/reply
'''

from __future__ import division

from . import data as bitcoin_data
from . import sha256
from p2pool.util import pack

def _swap4(s):
    if len(s) % 4:
        raise ValueError()
    return ''.join(s[x:x+4][::-1] for x in xrange(0, len(s), 4))

class BlockAttempt(object):
    def __init__(self, version, previous_block, merkle_root, timestamp, bits, share_target):
        self.version, self.previous_block, self.merkle_root, self.timestamp, self.bits, self.share_target = version, previous_block, merkle_root, timestamp, bits, share_target
    
    def __hash__(self):
        return hash((self.version, self.previous_block, self.merkle_root, self.timestamp, self.bits, self.share_target))
    
    def __eq__(self, other):
        if not isinstance(other, BlockAttempt):
            raise ValueError('comparisons only valid with other BlockAttempts')
        return self.__dict__ == other.__dict__
    
    def __ne__(self, other):
        return not (self == other)
    
    def __repr__(self):
        return 'BlockAttempt(%s)' % (', '.join('%s=%r' % (k, v) for k, v in self.__dict__.iteritems()),)
    
    def getwork(self, **extra):
        if 'data' in extra or 'hash1' in extra or 'target' in extra or 'midstate' in extra:
            raise ValueError()
        
        block_data = bitcoin_data.block_header_type.pack(dict(
            version=self.version,
            previous_block=self.previous_block,
            merkle_root=self.merkle_root,
            timestamp=self.timestamp,
            bits=self.bits,
            nonce=0,
        ))
        
        getwork = {
            'data': _swap4(block_data).encode('hex') + '000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000',
            'hash1': '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
            'target': pack.IntType(256).pack(self.share_target).encode('hex'),
            'midstate': _swap4(sha256.process(sha256.initial_state, block_data[:64])).encode('hex'),
        }
        
        getwork = dict(getwork)
        getwork.update(extra)
        
        return getwork
    
    @classmethod
    def from_getwork(cls, getwork):
        attrs = decode_data(getwork['data'])
        
        return cls(
            version=attrs['version'],
            previous_block=attrs['previous_block'],
            merkle_root=attrs['merkle_root'],
            timestamp=attrs['timestamp'],
            bits=attrs['bits'],
            share_target=pack.IntType(256).unpack(getwork['target'].decode('hex')),
        )
    
    def update(self, **kwargs):
        d = self.__dict__.copy()
        d.update(kwargs)
        return self.__class__(**d)

def decode_data(data):
    return bitcoin_data.block_header_type.unpack(_swap4(data.decode('hex'))[:80])
