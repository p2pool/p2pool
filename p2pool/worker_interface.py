from __future__ import division

import json
import random

from twisted.internet import defer

from p2pool.util import jsonrpc, deferred_resource

def get_id(request):
    return request.getClientIP(), request.getHeader('Authorization'), request.getHeader('User-Agent')

last_cache_invalidation = {}

class LongPollingWorkerInterface(deferred_resource.DeferredResource):
    def __init__(self, work, compute):
        self.work = work
        self.compute = compute
    
    @defer.inlineCallbacks
    def render_GET(self, request):
        id = random.randrange(10000)
        print "LONG POLL", id
        
        request_id = get_id(request)
        
        work = self.work.value
        thought_work = last_cache_invalidation.get(request_id, None)
        
        #if thought_work is not None and work != thought_work and work['previous_block'] == thought_work['previous_block']:
        #    # clients won't believe the update
        #    work = work.copy()
        #    work['previous_block'] = random.randrange(2**256)
        
        if work == thought_work:
            work = yield self.work.changed.get_deferred()
        else:
            print "shortcut worked!"
        
        thought_work = last_cache_invalidation.get(request_id, None)
        if thought_work is not None and work != thought_work and work['previous_block'] == thought_work['previous_block']:
            # clients won't believe the update
            work = work.copy()
            work['previous_block'] = random.randrange(2**256)
        
        res = self.compute(work, request.getHeader('X-All-Targets') is not None)
        
        last_cache_invalidation[request_id] = work
        
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('Content-Type', 'application/json')
        request.write(json.dumps({
            'jsonrpc': '2.0',
            'id': 0,
            'result': res.getwork(),
            'error': None,
        }))
        
        print "END POLL %i %x" % (id, work['best_share_hash'] % 2**32 if work['best_share_hash'] is not None else 0)
    render_POST = render_GET

class RateInterface(deferred_resource.DeferredResource):
    def __init__(self, get_rate):
        self.get_rate = get_rate
    
    def render_GET(self, request):
        request.setHeader('Content-Type', 'application/json')
        request.write(json.dumps(self.get_rate()))

class WorkerInterface(jsonrpc.Server):
    def __init__(self, work, compute, response_callback, get_rate):
        jsonrpc.Server.__init__(self)
        
        self.work = work
        self.compute = compute
        self.response_callback = response_callback
        self.get_rate = get_rate
        
        self.putChild('long-polling',
            LongPollingWorkerInterface(self.work, self.compute))
        self.putChild('rate',
            RateInterface(get_rate))
        self.putChild('', self)
    
    def rpc_getwork(self, request, data=None):
        request.setHeader('X-Long-Polling', '/long-polling')
        
        if data is not None:
            return self.response_callback(data)
        
        request_id = get_id(request)
        
        work = self.work.value
        thought_work = last_cache_invalidation.get(request_id, None)
        
        if thought_work is not None and work != thought_work and work['previous_block'] == thought_work['previous_block']:
            # clients won't believe the update
            work = work.copy()
            work['previous_block'] = random.randrange(2**256)
        
        res = self.compute(work, request.getHeader('X-All-Targets') is not None)
        
        last_cache_invalidation[request_id] = work
        
        return res.getwork()
    rpc_getwork.takes_request = True
