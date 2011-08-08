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

class GenericDeferrer(object):
    '''
    Converts query with identifier/got response interface to deferred interface
    '''
    
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
            df.errback(failure.Failure(defer.TimeoutError('in GenericDeferrer')))
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

class NotNowError(Exception):
    pass

class DeferredCacher(object):
    '''
    like memoize, but for functions that return Deferreds
    
    @DeferredCacher
    def f(x):
        ...
        return df
    
    @DeferredCacher.with_backing(bsddb.hashopen(...))
    def f(x):
        ...
        return df
    '''
    
    @classmethod
    def with_backing(cls, backing):
        return lambda func: cls(func, backing)
    
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
    
    def call_now(self, key):
        if key in self.waiting:
            raise NotNowError()
        
        if key in self.backing:
            return self.backing[key]
        else:
            self.waiting[key] = defer.Deferred()
            def cb(value):
                self.backing[key] = value
                self.waiting.pop(key).callback(None)
            def eb(fail):
                self.waiting.pop(key).callback(None)
                print
                print 'Error when requesting noncached value:'
                fail.printTraceback()
                print
            self.func(key).addCallback(cb).addErrback(eb)
            raise NotNowError()
