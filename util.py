import random

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
    
    def watch(self, func):
        self.observers.append(func)
    
    def watch_one_time(self, func):
        self.one_time_observers.append(func)
    
    def happened(self, event):
        for func in self.observers:
            func(event)
        
        one_time_observers = self.one_time_observers
        self.one_time_observers = []
        for func in one_time_observers:
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
            df.errback(fail.Failure(defer.TimeoutError()))
        timer = reactor.callLater(self.timeout, timeout)
        self.func(id, *args, **kwargs)
        self.map[id] = df, timer
        return df
    
    def gotResponse(self, id, resp):
        if id not in self.map:
            #print "got id without request", id, resp
            return # XXX
        df, timer = self.map.pop(id)
        timer.cancel()
        df.callback(resp)
    
def incr_dict(d, key, step=1):
    d = dict(d)
    if key not in d:
        d[key] = 0
    d[key] += 1
        return d
