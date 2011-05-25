import time
import collections

from twisted.internet import defer, reactor
from twisted.web import server, resource

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
        self.observers = []
        self.one_time_observers = []
    def watch(self, callable):
        self.observers.append(callable)
        return callable
    def watch_one_time(self, callable):
        self.one_time_observers.append(callable)
        return callable
    def happened(self, event):
        for callable in self.observers:
            callable(event)
        one_time_observers = self.one_time_observers
        self.one_time_observers = []
        for callable in one_time_observers:
            callable(event)
    def get_deferred(self):
        df = defer.Deferred()
        self.watch_one_time(df.callback)
        return df

class Variable(object):
    def __init__(self, value):
        self._value = value
        self.observers = []
    
    def get(self):
        return self._value
    
    def set(self, value):
        if value == self._value:
            return
        self._value = value
        
        observers = self.observers
        self.observers = []
        
        for observer in observers:
            observer(value)
    
    value = property(get, set)
    
    def watch(self, callback):
        self.observers.append(callback)
    
    def get_deferred(self):
        df = defer.Deferred()
        self.watch(df.callback)
        return df

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

class ExpiringDict(object):
    # XXX bad memory usage - O(activity rate * expiry_time)
    # could be improved using an updatable min-heap to remove duplication
    def __init__(self, expiry_time=600):
        self.d = {}
        self.expiry_time = expiry_time
        self.expiry_deque = collections.deque()
    
    def _expire(self):
        while self.expiry_deque and self.expiry_deque[0] < time.time() - self.expiry_time:
            timestamp, key = self.expiry_deque.popleft()
            if self.d[key][0] == timestamp:
                del self.d[key]
    
    def __getitem__(self, key):
        t = time.time()
        old_timestamp, value = self.d[key]
        self.d[key] = t, value
        self.expiry_deque.append((t, key))
        return value
    
    def __setitem__(self, key, value):
        t = time.time()
        self.d[key] = t, value
        self.expiry_deque.append((t, key))
    
    def __delitem__(self, key):
        del self.d[key]
    
    def setdefault(self, key, default_value):
        old_timestamp, value = self.d.get(key, (None, default_value))
        self[key] = value
        return value

def _DataChunker(receiver):
    wants = receiver.next()
    buf = ""
    
    while True:
        buf += yield
        pos = 0
        
        while True:
            if pos + wants > len(buf):
                break
            new_wants = receiver.send(buf[pos:pos + wants])
            pos += wants
            wants = new_wants
        
        buf = buf[pos:]

def DataChunker(receiver):
    x = _DataChunker(receiver)
    x.next()
    return x.send
