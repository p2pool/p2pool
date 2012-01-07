from __future__ import division

import StringIO
import json
import random
import weakref

from twisted.internet import defer

import p2pool
from p2pool.bitcoin import getwork
from p2pool.util import jsonrpc, variable

class _Page(jsonrpc.Server):
    def __init__(self, parent, long_poll):
        jsonrpc.Server.__init__(self)
        self.parent = parent
        self.long_poll = long_poll
    
    def rpc_getwork(self, request, data=None):
        return self.parent._getwork(request, data, long_poll=self.long_poll)
    
    def render_GET(self, request):
        request.content = StringIO.StringIO(json.dumps(dict(id=0, method='getwork')))
        return self.render_POST(request)

class WorkerBridge(object):
    def __init__(self):
        self.new_work_event = variable.Event()
    
    def preprocess_request(self, request):
        return request, # *args to self.compute
    
    def get_work(self, request):
        raise NotImplementedError()
    
    def got_response(self, block_header):
        print self.got_response, "called with", block_header

class WorkerInterface(object):
    def __init__(self, worker_bridge):
        self.worker_bridge = worker_bridge
        
        self.worker_views = {}
        
        self.work_cache = {} # request_process_func(request) -> blockattempt
        
        new_work_event = self.worker_bridge.new_work_event
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
            defer.returnValue(self.worker_bridge.got_response(getwork.decode_data(data), request))
        
        if p2pool.DEBUG:
            id = random.randrange(1000, 10000)
            print 'POLL %i START is_long_poll=%r user_agent=%r user=%r' % (id, long_poll, request.getHeader('User-Agent'), request.getUser())
        
        if long_poll:
            request_id = request.getClientIP(), request.getHeader('Authorization')
            if self.worker_views.get(request_id, self.worker_bridge.new_work_event.times) != self.worker_bridge.new_work_event.times:
                if p2pool.DEBUG:
                    print 'POLL %i PUSH' % (id,)
            else:
                if p2pool.DEBUG:
                    print 'POLL %i WAITING' % (id,)
                yield self.worker_bridge.new_work_event.get_deferred()
            self.worker_views[request_id] = self.worker_bridge.new_work_event.times
        
        key = self.worker_bridge.preprocess_request(request)
        
        if key in self.work_cache:
            res, orig_timestamp = self.work_cache.pop(key)
        else:
            res = self.worker_bridge.get_work(*key)
            orig_timestamp = res.timestamp
        
        if res.timestamp + 12 < orig_timestamp + 600:
            self.work_cache[key] = res.update(timestamp=res.timestamp + 12), orig_timestamp
        
        if p2pool.DEBUG:
            print 'POLL %i END identifier=%i' % (id, self.worker_bridge.new_work_event.times)
        
        defer.returnValue(res.getwork(identifier=str(self.worker_bridge.new_work_event.times)))
