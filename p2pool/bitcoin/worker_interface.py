from __future__ import division

import StringIO
import json
import random
import sys

from twisted.internet import defer

import p2pool
from p2pool.bitcoin import getwork
from p2pool.util import expiring_dict, jsonrpc, variable

class _Provider(object):
    def __init__(self, parent, long_poll):
        self.parent = parent
        self.long_poll = long_poll
    
    def rpc_getwork(self, request, data=None):
        return self.parent._getwork(request, data, long_poll=self.long_poll)

class _GETableServer(jsonrpc.Server):
    def __init__(self, provider, render_get_func):
        jsonrpc.Server.__init__(self, provider)
        self.render_GET = render_get_func

class WorkerBridge(object):
    def __init__(self):
        self.new_work_event = variable.Event()
    
    def preprocess_request(self, request):
        return request, # *args to self.compute
    
    def get_work(self, request):
        raise NotImplementedError()

class WorkerInterface(object):
    def __init__(self, worker_bridge):
        self.worker_bridge = worker_bridge
        
        self.worker_views = {}
        
        self.work_cache = {}
        self.work_cache_times = self.worker_bridge.new_work_event.times
        
        self.merkle_roots = expiring_dict.ExpiringDict(300)
    
    def attach_to(self, res, get_handler=None):
        res.putChild('', _GETableServer(_Provider(self, long_poll=False), get_handler))
        
        def repost(request):
            request.content = StringIO.StringIO(json.dumps(dict(id=0, method='getwork')))
            return s.render_POST(request)
        s = _GETableServer(_Provider(self, long_poll=True), repost)
        res.putChild('long-polling', s)
    
    @defer.inlineCallbacks
    def _getwork(self, request, data, long_poll):
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('X-Roll-NTime', 'expire=10')
        request.setHeader('X-Is-P2Pool', 'true')
        
        if data is not None:
            header = getwork.decode_data(data)
            if header['merkle_root'] not in self.merkle_roots:
                print >>sys.stderr, '''Couldn't link returned work's merkle root with its handler. This should only happen if this process was recently restarted!'''
                defer.returnValue(False)
            handler, orig_timestamp = self.merkle_roots[header['merkle_root']]
            dt = header['timestamp'] - orig_timestamp
            if dt < 0 or dt % 12 == 11 or dt >= 600:
                print >>sys.stderr, '''Miner %s @ %s rolled timestamp improperly! This may be a bug in the miner that is causing you to lose work!''' % (request.getUser(), request.getClientIP())
            defer.returnValue(handler(header, request))
        
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
        
        if self.work_cache_times != self.worker_bridge.new_work_event.times:
            self.work_cache = {}
            self.work_cache_times = self.worker_bridge.new_work_event.times
        
        if key in self.work_cache:
            res, orig_timestamp, handler = self.work_cache.pop(key)
        else:
            res, handler = self.worker_bridge.get_work(*key)
            assert res.merkle_root not in self.merkle_roots
            orig_timestamp = res.timestamp
        
        self.merkle_roots[res.merkle_root] = handler, orig_timestamp
        
        if res.timestamp + 12 < orig_timestamp + 600:
            self.work_cache[key] = res.update(timestamp=res.timestamp + 12), orig_timestamp, handler
        
        if p2pool.DEBUG:
            print 'POLL %i END identifier=%i' % (id, self.worker_bridge.new_work_event.times)
        
        defer.returnValue(res.getwork(identifier=str(self.worker_bridge.new_work_event.times), submitold=True))
