from __future__ import division

import json
import random

from twisted.internet import defer, reactor
from twisted.python import log

import p2pool
from p2pool.util import jsonrpc, deferred_resource, variable

# TODO: branch on User-Agent to remove overhead of workarounds

def get_memory(user_agent):
    user_agent2 = '' if user_agent is None else user_agent.lower()
    if 'java' in user_agent2: return 0 # hopefully diablominer...
    if 'cpuminer' in user_agent2: return 0
    if 'cgminer' in user_agent2: return 1
    if 'poclbm' in user_agent2: return 1
    if 'phoenix' in user_agent2: return 2
    print "Unknown miner User-Agent:", repr(user_agent)
    return 0

def get_id(request):
    return request.getClientIP(), request.getHeader('Authorization'), request.getHeader('User-Agent')

last_cache_invalidation = {} # XXX remove global

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
        try:
            try:
                id = random.randrange(10000)
                if p2pool.DEBUG:
                    print "LONG POLL", id
                
                request_id = get_id(request)
                memory = get_memory(request.getHeader('User-Agent'))
                
                if request_id not in last_cache_invalidation:
                    last_cache_invalidation[request_id] = variable.Variable((None, None))
                
                while True:
                    work = self.work.value
                    thought_work = last_cache_invalidation[request_id].value
                    if work != thought_work[-1]:
                        break
                    if p2pool.DEBUG:
                        print "POLL %i WAITING" % (id,)
                    yield defer.DeferredList([self.work.changed.get_deferred(), last_cache_invalidation[request_id].changed.get_deferred()], fireOnOneCallback=True)
                
                if thought_work[-1] is not None and work != thought_work[-1] and any(x is None or work['previous_block'] == x['previous_block'] for x in thought_work[-memory or len(thought_work):]):
                    # clients won't believe the update
                    newwork = work.copy()
                    newwork['previous_block'] = random.randrange(2**256)
                    if p2pool.DEBUG:
                        print "longpoll faked", id
                    res = self.compute(work, request.getHeader('X-All-Targets') is not None)
                    newres = self.compute(newwork, request.getHeader('X-All-Targets') is not None)
                else:
                    newwork = work
                    newres = res = self.compute(work, request.getHeader('X-All-Targets') is not None)
                
                reactor.callLater(.01, lambda: last_cache_invalidation[request_id].set((thought_work[-1], newwork)))
                
                request.setHeader('X-Long-Polling', '/long-polling')
                request.setHeader('Content-Type', 'application/json')
                request.write(json.dumps({
                    'jsonrpc': '2.0',
                    'id': 0,
                    'result': merge(newres.getwork(), res.getwork()),
                    'error': None,
                }))
            except jsonrpc.Error:
                raise
            except Exception:
                log.err(None, 'Squelched long polling error:')
                raise jsonrpc.Error(-32099, u'Unknown error')
        
        except jsonrpc.Error, e:
            request.write(json.dumps({
                'jsonrpc': '2.0',
                'id': 0,
                'result': None,
                'error': e._to_obj(),
            }))
        
        
        if p2pool.DEBUG:
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
        memory = get_memory(request.getHeader('User-Agent'))
        
        if request_id not in last_cache_invalidation:
            last_cache_invalidation[request_id] = variable.Variable((None, None))
        
        work = self.work.value
        thought_work = last_cache_invalidation[request_id].value
        
        if thought_work[-1] is not None and work != thought_work[-1] and any(x is None or work['previous_block'] == x['previous_block'] for x in thought_work[-memory or len(thought_work):]):
            # clients won't believe the update
            newwork = work.copy()
            newwork['previous_block'] = random.randrange(2**256)
            if p2pool.DEBUG:
                print "getwork faked"
            res = self.compute(work, request.getHeader('X-All-Targets') is not None)
            newres = self.compute(newwork, request.getHeader('X-All-Targets') is not None)
        else:
            newwork = work
            newres = res = self.compute(work, request.getHeader('X-All-Targets') is not None)
        
        reactor.callLater(.01, lambda: last_cache_invalidation[request_id].set((thought_work[-1], newwork)))
        if p2pool.DEBUG:
            print "END GETWORK %i" % (work['best_share_hash'] % 2**32 if work['best_share_hash'] is not None else 0,)
        
        return merge(newres.getwork(), res.getwork())
    rpc_getwork.takes_request = True
