from __future__ import division

import base64
import random
import weakref

from twisted.internet import defer

import p2pool
from p2pool import data as p2pool_data
from p2pool.bitcoin import getwork
from p2pool.util import jsonrpc, variable

def get_username(request):
    try:
        return base64.b64decode(request.getHeader('Authorization').split(' ', 1)[1]).split(':')[0]
    except: # XXX
        return None

class _Page(jsonrpc.Server):
    def __init__(self, parent, long_poll):
        jsonrpc.Server.__init__(self)
        self.parent = parent
        self.long_poll = long_poll
    
    def rpc_getwork(self, request, data=None):
        return self.parent._getwork(request, data, long_poll=self.long_poll)

class WorkerInterface(object):
    def __init__(self, compute, response_callback, new_work_event=variable.Event()):
        self.compute = compute
        self.response_callback = response_callback
        self.new_work_event = new_work_event
        
        self.worker_views = {}
        
        self.work_cache = {} # username -> (blockattempt, work-identifier-string)
        watch_id = new_work_event.watch(lambda *args: self_ref().work_cache.clear())
        self_ref = weakref.ref(self, lambda _: new_work_event.unwatch(watch_id))
    
    def attach_to(self, res):
        res.putChild('', _Page(self, long_poll=False))
        res.putChild('long-polling', _Page(self, long_poll=True))
    
    @defer.inlineCallbacks
    def _getwork(self, request, data, long_poll):
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('X-Roll-NTime', 'expire=10')
        
        if data is not None:
            defer.returnValue(self.response_callback(getwork.decode_data(data), request))
        
        if p2pool.DEBUG:
            id = random.randrange(1000, 10000)
            print 'POLL %i START long_poll=%r user_agent=%r x-work-identifier=%r user=%r' % (id, long_poll, request.getHeader('User-Agent'), request.getHeader('X-Work-Identifier'), get_username(request))
        
        if long_poll:
            request_id = request.getClientIP(), request.getHeader('Authorization')
            if self.worker_views.get(request_id, self.new_work_event.times) != self.new_work_event.times:
                if p2pool.DEBUG:
                    print 'POLL %i PUSH user=%r' % (id, get_username(request))
            else:
                if p2pool.DEBUG:
                    print 'POLL %i WAITING user=%r' % (id, get_username(request))
                yield self.new_work_event.get_deferred()
                self.worker_views[request_id] = self.new_work_event.times
        
        username = get_username(request)
        
        if username in self.work_cache:
            res, identifier = self.work_cache[username]
        else:
            res, identifier = self.compute(username)
        
        self.work_cache[username] = res.update(timestamp=res.timestamp + 12), identifier # XXX doesn't bound timestamp
        
        if p2pool.DEBUG:
            print 'POLL %i END %s user=%r' % (id, p2pool_data.format_hash(identifier), get_username(request)) # XXX identifier is hack
        
        defer.returnValue(res.getwork(identifier=str(identifier)))
