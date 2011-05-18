from twisted.internet import defer, reactor
from twisted.web import server, resource

class DeferredResource(resource.Resource):
    def render(self, request): 
        def finish(x):
            if x is not None:
                request.write(x)
            request.finish()
        def finish_error(x):
            request.setResponseCode(500) # won't do anything if already written to
            request.write("---ERROR---")
            request.finish()
            return x # prints traceback
        defer.maybeDeferred(resource.Resource.render, self, request).addCallbacks(finish, finish_error)
        return server.NOT_DONE_YET

class Variable(object):
    def __init__(self, value):
        self._value = value
        self.observers = set()
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
