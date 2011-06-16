from __future__ import division

import collections
import hashlib
import itertools
import random

from twisted.internet import defer, reactor
from twisted.python import failure
from twisted.web import resource, server

class DeferredResource(resource.Resource):
    def render(self, request):
        def finish(x):
            if x is not None:
                request.write(x)
            request.finish()
        
        def finish_error(fail):
            request.setResponseCode(500) # won't do anything if already written to
            request.write("---ERROR---")
            request.finish()
            fail.printTraceback()
        
        defer.maybeDeferred(resource.Resource.render, self, request).addCallbacks(finish, finish_error)
        return server.NOT_DONE_YET

class Event(object):
    def __init__(self):
        self.observers = {}
        self.one_time_observers = {}
        self.id_generator = itertools.count()
    
    def watch(self, func):
        id = self.id_generator.next()
        self.observers[id] = func
        return id
    def unwatch(self, id):
        self.observers.pop(id)
    
    def watch_one_time(self, func):
        id = self.id_generator.next()
        self.one_time_observers[id] = func
        return id
    def unwatch_one_time(self, id):
        self.one_time_observers.pop(id)
    
    def happened(self, event=None):
        for func in self.observers.itervalues():
            func(event)
        
        one_time_observers = self.one_time_observers
        self.one_time_observers = {}
        for func in one_time_observers.itervalues():
            func(event)
    
    def get_deferred(self):
        df = defer.Deferred()
        self.watch_one_time(df.callback)
        return df

class Variable(object):
    def __init__(self, value):
        self.value = value
        self.changed = Event()
    
    def set(self, value):
        if value == self.value:
            return
        
        self.value = value
        self.changed.happened(value)

def sleep(t):
    d = defer.Deferred()
    reactor.callLater(t, d.callback, None)
    return d

def median(x):
    # don't really need a complex algorithm here
    y = sorted(x)
    left = (len(y) - 1)//2
    right = len(y)//2
    return (y[left] + y[right])/2

class StringBuffer(object):
    "Buffer manager with great worst-case behavior"
    
    def __init__(self, data=""):
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
            raise IndexError("not enough data")
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
    """
    Produces a function that accepts data that is input into a generator
    (receiver) in response to the receiver yielding the size of data to wait on
    """
    x = _DataChunker(receiver)
    x.next()
    return x.send

class ReplyMatcher(object):
    def __init__(self, func, timeout=5):
        self.func = func
        self.timeout = timeout
        self.map = {}
    
    def __call__(self, id):
        try:
            self.func(id)
            uniq = random.randrange(2**256)
            df = defer.Deferred()
            def timeout():
                df, timer = self.map[id].pop(uniq)
                df.errback(failure.Failure(defer.TimeoutError()))
                if not self.map[id]:
                    del self.map[id]
            self.map.setdefault(id, {})[uniq] = (df, reactor.callLater(self.timeout, timeout))
            return df
        except:
            import traceback
            traceback.print_exc()
    
    def got_response(self, id, resp):
        if id not in self.map:
            return
        for df, timer in self.map.pop(id).itervalues():
            timer.cancel()
            df.callback(resp)

class GenericDeferrer(object):
    def __init__(self, max_id, func, timeout=5):
        self.max_id = max_id
        self.func = func
        self.timeout = timeout
        self.map = {}
    
    def __call__(self, *args, **kwargs):
        while True:
            id = random.randrange(self.max_id)
            if id not in self.map:
                break
        df = defer.Deferred()
        def timeout():
            self.map.pop(id)
            df.errback(failure.Failure(defer.TimeoutError()))
        timer = reactor.callLater(self.timeout, timeout)
        self.func(id, *args, **kwargs)
        self.map[id] = df, timer
        return df
    
    def got_response(self, id, resp):
        if id not in self.map:
            return
        df, timer = self.map.pop(id)
        timer.cancel()
        df.callback(resp)

class DeferredCacher(object):
    def __init__(self, func, backing=None):
        if backing is None:
            backing = {}
        
        self.func = func
        self.backing = backing
        self.waiting = {}
    
    @defer.inlineCallbacks
    def __call__(self, key):
        if key in self.waiting:
            yield self.waiting[key]
        
        if key in self.backing:
            defer.returnValue(self.backing[key])
        else:
            self.waiting[key] = defer.Deferred()
            try:
                value = yield self.func(key)
            finally:
                self.waiting.pop(key).callback(None)
        
        self.backing[key] = value
        defer.returnValue(value)

def pubkey_to_address(pubkey, testnet):
    if len(pubkey) != 65:
        raise ValueError("invalid pubkey")
    version = 111 if testnet else 0
    key_hash = chr(version) + hashlib.new('ripemd160', hashlib.sha256(pubkey).digest()).digest()
    checksum = hashlib.sha256(hashlib.sha256(key_hash).digest()).digest()[:4]
    return base58_encode(key_hash + checksum)

def base58_encode(data):
    return "1"*(len(data) - len(data.lstrip(chr(0)))) + natural_to_string(string_to_natural(data), "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")

def natural_to_string(n, alphabet=None, min_width=1):
    if alphabet is None:
        s = '%x' % (n,)
        if len(s) % 2:
            s = '\0' + x
        return s.decode('hex').rjust(min_width, '\x00')
    res = []
    while n:
        n, x = divmod(n, len(alphabet))
        res.append(alphabet[x])
    res.reverse()
    return ''.join(res).rjust(min_width, '\x00')

def string_to_natural(s, alphabet=None):
    if alphabet is None:
        s = s.encode('hex')
        return int(s, 16)
    if not s or (s != alphabet[0] and s.startswith(alphabet[0])):
        raise ValueError()
    return sum(alphabet.index(char) * len(alphabet)**i for i, char in enumerate(reversed(s)))


class DictWrapper(object):
    def encode_key(self, key):
        return key
    def decode_key(self, encoded_key):
        return encoded_key
    def encode_value(self, value):
        return value
    def decode_value(self, encoded_value):
        return encoded_value
    
    def __init__(self, inner):
        self.inner = inner
    
    def __len__(self):
        return len(self.inner)
    
    def __contains__(self, key):
        return self.encode_key(key) in self.inner
    
    def __getitem__(self, key):
        return self.decode_value(self.inner[self.encode_key(key)])
    
    def __setitem__(self, key, value):
        self.inner[self.encode_key(key)] = self.encode_value(value)
    
    def __delitem__(self, key):
        del self.inner[self.encode_key(key)]
    
    def keys(self):
        return map(self.decode_key, self.inner.keys())
