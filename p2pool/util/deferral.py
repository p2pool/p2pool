from __future__ import division

import itertools
import random
import sys

from twisted.internet import defer, reactor
from twisted.python import failure, log

def sleep(t):
    d = defer.Deferred()
    reactor.callLater(t, d.callback, None)
    return d

def run_repeatedly(f, *args, **kwargs):
    current_dc = [None]
    def step():
        delay = f(*args, **kwargs)
        current_dc[0] = reactor.callLater(delay, step)
    step()
    def stop():
        current_dc[0].cancel()
    return stop

class RetrySilentlyException(Exception):
    pass

def retry(message='Error:', delay=3, max_retries=None, traceback=True):
    '''
    @retry('Error getting block:', 1)
    @defer.inlineCallbacks
    def get_block(hash):
        ...
    '''
    
    def retry2(func):
        @defer.inlineCallbacks
        def f(*args, **kwargs):
            for i in itertools.count():
                try:
                    result = yield func(*args, **kwargs)
                except Exception, e:
                    if i == max_retries:
                        raise
                    if not isinstance(e, RetrySilentlyException):
                        if traceback:
                            log.err(None, message)
                        else:
                            print >>sys.stderr, message, e
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

class GenericDeferrer(object):
    '''
    Converts query with identifier/got response interface to deferred interface
    '''
    
    def __init__(self, max_id, func, timeout=5, on_timeout=lambda: None):
        self.max_id = max_id
        self.func = func
        self.timeout = timeout
        self.on_timeout = on_timeout
        self.map = {}
    
    def __call__(self, *args, **kwargs):
        while True:
            id = random.randrange(self.max_id)
            if id not in self.map:
                break
        def cancel(df):
            df, timer = self.map.pop(id)
            timer.cancel()
        try:
            df = defer.Deferred(cancel)
        except TypeError:
            df = defer.Deferred() # handle older versions of Twisted
        def timeout():
            self.map.pop(id)
            df.errback(failure.Failure(defer.TimeoutError('in GenericDeferrer')))
            self.on_timeout()
        timer = reactor.callLater(self.timeout, timeout)
        self.map[id] = df, timer
        self.func(id, *args, **kwargs)
        return df
    
    def got_response(self, id, resp):
        if id not in self.map:
            return
        df, timer = self.map.pop(id)
        timer.cancel()
        df.callback(resp)
    
    def respond_all(self, resp):
        while self.map:
            id, (df, timer) = self.map.popitem()
            timer.cancel()
            df.errback(resp)

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
    
    _nothing = object()
    def call_now(self, key, default=_nothing):
        if key in self.backing:
            return self.backing[key]
        if key not in self.waiting:
            self.waiting[key] = defer.Deferred()
            def cb(value):
                self.backing[key] = value
                self.waiting.pop(key).callback(None)
            def eb(fail):
                self.waiting.pop(key).callback(None)
                if fail.check(RetrySilentlyException):
                    return
                print
                print 'Error when requesting noncached value:'
                fail.printTraceback()
                print
            self.func(key).addCallback(cb).addErrback(eb)
        if default is not self._nothing:
            return default
        raise NotNowError(key)
