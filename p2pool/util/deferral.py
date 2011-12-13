from __future__ import division

import random

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
        self.func(id)
        uniq = random.randrange(2**256)
        df = defer.Deferred()
        def timeout():
            df, timer = self.map[id].pop(uniq)
            df.errback(failure.Failure(defer.TimeoutError('in ReplyMatcher')))
            if not self.map[id]:
                del self.map[id]
        self.map.setdefault(id, {})[uniq] = (df, reactor.callLater(self.timeout, timeout))
        return df
    
    def got_response(self, id, resp):
        if id not in self.map:
            return
        for df, timer in self.map.pop(id).itervalues():
            timer.cancel()
            df.callback(resp)
