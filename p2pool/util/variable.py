import itertools
import weakref

from twisted.internet import defer, reactor
from twisted.python import failure, log

class Event(object):
    def __init__(self):
        self.observers = {}
        self.id_generator = itertools.count()
        self._once = None
        self.times = 0
    
    def run_and_watch(self, func):
        func()
        return self.watch(func)
    def watch_weakref(self, obj, func):
        # func must not contain a reference to obj!
        watch_id = self.watch(lambda *args: func(obj_ref(), *args))
        obj_ref = weakref.ref(obj, lambda _: self.unwatch(watch_id))
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
        self.times += 1
        
        once, self._once = self._once, None
        
        for id, func in sorted(self.observers.iteritems()):
            try:
                func(*event)
            except:
                log.err(None, "Error while processing Event callbacks:")
        
        if once is not None:
            once.happened(*event)
    
    def get_deferred(self, timeout=None):
        once = self.once
        df = defer.Deferred()
        id1 = once.watch(lambda *event: df.callback(event))
        if timeout is not None:
            def do_timeout():
                df.errback(failure.Failure(defer.TimeoutError('in Event.get_deferred')))
                once.unwatch(id1)
                once.unwatch(x)
            delay = reactor.callLater(timeout, do_timeout)
            x = once.watch(lambda *event: delay.cancel())
        return df

class Variable(object):
    def __init__(self, value):
        self.value = value
        self.changed = Event()
        self.transitioned = Event()
    
    def set(self, value):
        if value == self.value:
            return
        
        oldvalue = self.value
        self.value = value
        self.changed.happened(value)
        self.transitioned.happened(oldvalue, value)
    
    @defer.inlineCallbacks
    def get_when_satisfies(self, func):
        while True:
            if func(self.value):
                defer.returnValue(self.value)
            yield self.changed.once.get_deferred()
    
    def get_not_none(self):
        return self.get_when_satisfies(lambda val: val is not None)

class VariableDict(Variable):
    def __init__(self, value):
        Variable.__init__(self, value)
        self.added = Event()
        self.removed = Event()
    
    def add(self, values):
        new_items = dict([item for item in values.iteritems() if not item[0] in self.value or self.value[item[0]] != item[1]])
        self.value.update(values)
        self.added.happened(new_items)
        # XXX call self.changed and self.transitioned
    
    def remove(self, values):
        gone_items = dict([item for item in values.iteritems() if item[0] in self.value])
        for key in gone_keys:
            del self.values[key]
        self.removed.happened(new_items)
        # XXX call self.changed and self.transitioned
