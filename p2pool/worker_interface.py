from __future__ import division

import json
import random

from twisted.internet import defer

from p2pool.util import jsonrpc, deferred_resource, variable

def get_id(request):
    x = request.getClientIP(), request.getHeader('Authorization'), request.getHeader('User-Agent')
    print x
    return x

last_cache_invalidation = {}

def merge(gw1, gw2):
    if gw1['hash1'] != gw2['hash1']:
        raise ValueError()
    if gw1['target'] != gw2['target']:
        raise ValueError()
    return dict(
        data=gw1['data'],
        midstate=gw2['midstate'],
        hash1=gw1['hash1'],
        target=gw1['target'],
    )
    

class LongPollingWorkerInterface(deferred_resource.DeferredResource):
    def __init__(self, work, compute):
        self.work = work
        self.compute = compute
    
    @defer.inlineCallbacks
    def render_GET(self, request):
        id = random.randrange(10000)
        print "LONG POLL", id
        
        request_id = get_id(request)
        
        if request_id not in last_cache_invalidation:
            last_cache_invalidation[request_id] = variable.Variable((None, None))
        
        while True:
            work = self.work.value
            thought_work = last_cache_invalidation[request_id].value
            if work != thought_work[-1]:
                break
            yield defer.DeferredList([self.work.changed.get_deferred(), last_cache_invalidation[request_id].changed.get_deferred()], fireOnOneCallback=True)
        
        if thought_work[-1] is not None and work != thought_work[-1] and any(work['previous_block'] == x['previous_block'] for x in thought_work):
            # clients won't believe the update
            newwork = work.copy()
            newwork['previous_block'] = random.randrange(2**256)
            print "longpoll faked"
            res = self.compute(work, request.getHeader('X-All-Targets') is not None)
            newres = self.compute(newwork, request.getHeader('X-All-Targets') is not None)
        else:
            newwork = work
            newres = res = self.compute(work, request.getHeader('X-All-Targets') is not None)
        
        last_cache_invalidation[request_id].set((thought_work[-1], newwork))
        
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('Content-Type', 'application/json')
        request.write(json.dumps({
            'jsonrpc': '2.0',
            'id': 0,
            'result': merge(newres.getwork(), res.getwork()),
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
        
        if request_id not in last_cache_invalidation:
            last_cache_invalidation[request_id] = variable.Variable((None, None))
        
        work = self.work.value
        thought_work = last_cache_invalidation[request_id].value
        
        if thought_work[-1] is not None and work != thought_work[-1] and any(work['previous_block'] == x['previous_block'] for x in thought_work):
            # clients won't believe the update
            newwork = work.copy()
            newwork['previous_block'] = random.randrange(2**256)
            print "longpoll faked"
            res = self.compute(work, request.getHeader('X-All-Targets') is not None)
            newres = self.compute(newwork, request.getHeader('X-All-Targets') is not None)
        else:
            newwork = work
            newres = res = self.compute(work, request.getHeader('X-All-Targets') is not None)
        
        last_cache_invalidation[request_id].set((thought_work[-1], newwork))
        
        return merge(newres.getwork(), res.getwork())
    rpc_getwork.takes_request = True
