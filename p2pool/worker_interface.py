from __future__ import division

import base64
import json
import random

from twisted.internet import defer, reactor
from twisted.python import log

import p2pool
from p2pool import data as p2pool_data
from p2pool.util import jsonrpc, deferred_resource, variable
from p2pool.bitcoin import data as bitcoin_data

def get_payout_script(request, net):
    try:
        user = base64.b64decode(request.getHeader('Authorization').split(' ', 1)[1]).split(':')[0]
        return bitcoin_data.pubkey_hash_to_script2(bitcoin_data.address_to_pubkey_hash(user, net))
    except: # XXX blah
        return None

def get_memory(request):
    if request.getHeader('X-Work-Identifier') is not None:
        return 0
    user_agent = request.getHeader('User-Agent')
    user_agent2 = '' if user_agent is None else user_agent.lower()
    if 'java' in user_agent2: return 0 # hopefully diablominer...
    if 'cpuminer' in user_agent2: return 0
    if 'ufasoft' in user_agent2: return 0 # not confirmed
    if 'cgminer' in user_agent2: return 1
    if 'poclbm' in user_agent2: return 1
    if 'phoenix' in user_agent2: return 2
    print 'Unknown miner User-Agent:', repr(user_agent)
    return 0

def get_id(request):
    return request.getClientIP(), request.getHeader('Authorization'), request.getHeader('User-Agent')

last_cache_invalidation = {} # XXX remove global
holds = {}

@defer.inlineCallbacks
def wait_hold(request_id):
    while request_id in holds:
        yield holds[request_id].get_deferred()

def set_hold(request_id, dt):
    if request_id in holds:
        raise ValueError('hold already present!')
    holds[request_id] = variable.Event()
    holds[request_id].status = 0
    def cb():
        if holds[request_id].status != 0:
            raise AssertionError()
        holds[request_id].status = 1
        holds.pop(request_id).happened()
    reactor.callLater(dt, cb)

class LongPollingWorkerInterface(deferred_resource.DeferredResource):
    def __init__(self, work, compute, net):
        self.work = work
        self.compute = compute
        self.net = net
    
    @defer.inlineCallbacks
    def render_GET(self, request):
        try:
            try:
                request.setHeader('X-Long-Polling', '/long-polling')
                request.setHeader('Content-Type', 'application/json')
                
                id = random.randrange(10000)
                if p2pool.DEBUG:
                    print 'POLL %i START' % (id,)
                
                request_id = get_id(request)
                memory = get_memory(request)
                
                if request_id not in last_cache_invalidation:
                    last_cache_invalidation[request_id] = variable.Variable((None, None))
                
                while True:
                    yield wait_hold(request_id)
                    work = self.work.value
                    thought_work = last_cache_invalidation[request_id].value
                    if work != thought_work[-1]:
                        break
                    if p2pool.DEBUG:
                        print 'POLL %i WAITING' % (id,)
                    yield defer.DeferredList([self.work.changed.get_deferred(), last_cache_invalidation[request_id].changed.get_deferred()], fireOnOneCallback=True)
                
                if thought_work[-1] is not None and work != thought_work[-1] and any(x is None or work['previous_block'] == x['previous_block'] for x in thought_work[-memory or len(thought_work):]):
                    # clients won't believe the update
                    work = work.copy()
                    work['previous_block'] = random.randrange(2**256)
                    if p2pool.DEBUG:
                        print 'POLL %i FAKED' % (id,)
                    set_hold(request_id, .01)
                res = self.compute(work, get_payout_script(request, self.net))
                
                last_cache_invalidation[request_id].set((thought_work[-1], work))
                if p2pool.DEBUG:
                    print 'POLL %i END %s' % (id, p2pool_data.format_hash(work['best_share_hash']))
                
                if request.getHeader('X-All-Targets') is None and res.target2 > 2**256//2**32 - 1:
                    res = res.update(target2=2**256//2**32 - 1)
                
                request.write(json.dumps({
                    'jsonrpc': '2.0',
                    'id': 0,
                    'result': res.getwork(identifier=str(work['best_share_hash'])),
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
    render_POST = render_GET

class RateInterface(deferred_resource.DeferredResource):
    def __init__(self, get_rate):
        self.get_rate = get_rate
    
    def render_GET(self, request):
        request.setHeader('Content-Type', 'application/json')
        request.write(json.dumps(self.get_rate()))

class WorkerInterface(jsonrpc.Server):
    def __init__(self, work, compute, response_callback, get_rate, get_users, net):
        jsonrpc.Server.__init__(self)
        
        self.work = work
        self.compute = compute
        self.response_callback = response_callback
        self.net = net
        
        self.putChild('long-polling',
            LongPollingWorkerInterface(self.work, self.compute, net))
        self.putChild('rate',
            RateInterface(get_rate))
        self.putChild('users',
            RateInterface(get_users))
        self.putChild('', self)
    
    @defer.inlineCallbacks
    def rpc_getwork(self, request, data=None):
        request.setHeader('X-Long-Polling', '/long-polling')
        
        if data is not None:
            defer.returnValue(self.response_callback(data))
        
        request_id = get_id(request)
        memory = get_memory(request)
        
        if request_id not in last_cache_invalidation:
            last_cache_invalidation[request_id] = variable.Variable((None, None))
        
        yield wait_hold(request_id)
        work = self.work.value
        thought_work = last_cache_invalidation[request_id].value
        
        if thought_work[-1] is not None and work != thought_work[-1] and any(x is None or work['previous_block'] == x['previous_block'] for x in thought_work[-memory or len(thought_work):]):
            # clients won't believe the update
            work = work.copy()
            work['previous_block'] = random.randrange(2**256)
            if p2pool.DEBUG:
                print 'GETWORK FAKED'
            set_hold(request_id, .01) # guarantee ordering
        res = self.compute(work, get_payout_script(request, self.net))
        
        last_cache_invalidation[request_id].set((thought_work[-1], work))
        if p2pool.DEBUG:
            print 'GETWORK END %s' % (p2pool_data.format_hash(work['best_share_hash']),)
        
        if request.getHeader('X-All-Targets') is None and res.target2 > 2**256//2**32 - 1:
            res = res.update(target2=2**256//2**32 - 1)
        
        defer.returnValue(res.getwork(identifier=str(work['best_share_hash'])))
    rpc_getwork.takes_request = True
