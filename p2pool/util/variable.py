import itertools

from twisted.internet import defer, reactor
from twisted.python import failure

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
    
    def get_deferred(self, timeout=None):
        df = defer.Deferred()
        id1 = self.watch_one_time(df.callback)
        if timeout is not None:
            def do_timeout():
                df.errback(failure.Failure(defer.TimeoutError()))
                self.unwatch_one_time(id1)
                self.unwatch_one_time(x)
            delay = reactor.callLater(timeout, do_timeout)
            x = self.watch_one_time(lambda value: delay.cancel())
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
            self.changed.watch_one_time(df.callback)
            return df
