import itertools

from twisted.internet import defer, reactor
from twisted.python import failure, log

class Event(object):
    def __init__(self):
        self.observers = {}
        self.id_generator = itertools.count()
        self._once = None
    
    def watch(self, func):
        id = self.id_generator.next()
        self.observers[id] = func
        return id
    def unwatch(self, id):
        self.observers.pop(id)
    
    @property
    def once(self):
        res = self._once
        if res is None:
            res = self._once = Event()
        return res
    
    def happened(self, *event):
        for id, func in sorted(self.observers.iteritems()):
            try:
                func(*event)
            except:
                log.err(None, "Error while processing Event callbacks:")
        
        if self._once is not None:
            self._once.happened(*event)
            self._once = None
    
    def get_deferred(self, timeout=None):
        once = self.once
        df = defer.Deferred()
        id1 = once.watch(lambda *event: df.callback(event))
        if timeout is not None:
            def do_timeout():
                df.errback(failure.Failure(defer.TimeoutError()))
                once.unwatch(id1)
                once.unwatch(x)
            delay = reactor.callLater(timeout, do_timeout)
            x = once.watch(lambda *event: delay.cancel())
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
    
    def get_not_none(self):
        if self.value is not None:
            return defer.succeed(self.value)
        else:
            df = defer.Deferred()
            self.changed.once.watch(df.callback)
            return df
