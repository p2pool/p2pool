from __future__ import division

from twisted.internet import defer, reactor
from twisted.python import failure, log

def sleep(t):
    d = defer.Deferred()
    reactor.callLater(t, d.callback, None)
    return d

def retry(message, delay):
    '''
    @retry('Error getting block:', 1)
    @defer.inlineCallbacks
    def get_block(hash):
        ...
    '''
    
    def retry2(func):
        @defer.inlineCallbacks
        def f(*args, **kwargs):
            while True:
                try:
                    result = yield func(*args, **kwargs)
                except:
                    log.err(None, message)
                    yield sleep(delay)
                else:
                    defer.returnValue(result)
        return f
    return retry2

class ReplyMatcher(object):
    '''
    Converts request/got response interface to deferred interface
    '''
    
    def __init__(self, func, timeout=5):
        self.func = func
        self.timeout = timeout
        self.map = {}
    
    def __call__(self, id):
        if id not in self.map:
            self.func(id)
        df = defer.Deferred()
        def timeout():
            self.map[id].remove((df, timer))
            if not self.map[id]:
                del self.map[id]
            df.errback(failure.Failure(defer.TimeoutError('in ReplyMatcher')))
        timer = reactor.callLater(self.timeout, timeout)
        self.map.setdefault(id, set()).add((df, timer))
        return df
    
    def got_response(self, id, resp):
        if id not in self.map:
            return
        for df, timer in self.map.pop(id):
            df.callback(resp)
            timer.cancel()
