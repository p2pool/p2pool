import collections

class StringBuffer(object):
    'Buffer manager with great worst-case behavior'
    
    def __init__(self, data=''):
        self.buf = collections.deque([data])
        self.buf_len = len(data)
        self.pos = 0
    
    def __len__(self):
        return self.buf_len - self.pos
    
    def add(self, data):
        self.buf.append(data)
        self.buf_len += len(data)
    
    def get(self, wants):
        if self.buf_len - self.pos < wants:
            raise IndexError('not enough data')
        data = []
        while wants:
            seg = self.buf[0][self.pos:self.pos+wants]
            self.pos += len(seg)
            while self.buf and self.pos >= len(self.buf[0]):
                x = self.buf.popleft()
                self.buf_len -= len(x)
                self.pos -= len(x)
            
            data.append(seg)
            wants -= len(seg)
        return ''.join(data)

def _DataChunker(receiver):
    wants = receiver.next()
    buf = StringBuffer()
    
    while True:
        if len(buf) >= wants:
            wants = receiver.send(buf.get(wants))
        else:
            buf.add((yield))
def DataChunker(receiver):
    '''
    Produces a function that accepts data that is input into a generator
    (receiver) in response to the receiver yielding the size of data to wait on
    '''
    x = _DataChunker(receiver)
    x.next()
    return x.send
