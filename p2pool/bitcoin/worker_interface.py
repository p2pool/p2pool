from __future__ import division

import base64
import json
import random

from twisted.internet import defer, reactor
from twisted.python import log

import p2pool
from p2pool import data as p2pool_data
from p2pool.util import jsonrpc, deferred_resource, variable
from p2pool.bitcoin import getwork

def get_memory(request):
    if request.getHeader('X-Miner-Extensions') is not None and 'workidentifier' in request.getHeader('X-Miner-Extensions').split(' '):
        return 0
    if request.getHeader('X-Work-Identifier') is not None:
        return 0
    user_agent = request.getHeader('User-Agent')
    user_agent2 = '' if user_agent is None else user_agent.lower()
    if 'java' in user_agent2 or 'diablominer' in user_agent2: return 0 # hopefully diablominer...
    if 'cpuminer' in user_agent2: return 0
    if 'tenebrix miner' in user_agent2: return 0
    if 'ufasoft' in user_agent2: return 0 # not confirmed
    if 'cgminer' in user_agent2: return 1
    if 'poclbm' in user_agent2: return 1
    if 'phoenix' in user_agent2: return 2
    print 'Unknown miner User-Agent:', repr(user_agent)
    return 0

def get_max_target(request): # inclusive
    if request.getHeader('X-All-Targets') is not None or (request.getHeader('X-Miner-Extensions') is not None and 'alltargets' in request.getHeader('X-Miner-Extensions')):
        return 2**256-1
    user_agent = request.getHeader('User-Agent')
    user_agent2 = '' if user_agent is None else user_agent.lower()
    if 'java' in user_agent2 or 'diablominer' in user_agent2: return 2**256//2**32-1 # hopefully diablominer...
    if 'cpuminer' in user_agent2: return 2**256//2**32-1
    if 'tenebrix miner' in user_agent2: return 2**256-1
    if 'cgminer' in user_agent2: return 2**256//2**32-1
    if 'poclbm' in user_agent2: return 2**256//2**32-1
    if 'phoenix' in user_agent2: return 2**256//2**32-1
    print 'Unknown miner User-Agent:', repr(user_agent)
    return 2**256//2**32-1

def get_username(request):
    try:
        return base64.b64decode(request.getHeader('Authorization').split(' ', 1)[1]).split(':')[0]
    except: # XXX
        return None

def get_id(request):
    return request.getClientIP(), request.getHeader('Authorization')

class Holds(object):
    def __init__(self):
        self.holds = {}
    
    @defer.inlineCallbacks
    def wait_hold(self, request_id):
        while request_id in self.holds:
            yield self.holds[request_id].get_deferred()
    
    def set_hold(self, request_id, dt):
        if request_id in self.holds:
            raise ValueError('hold already present!')
        self.holds[request_id] = variable.Event()
        self.holds[request_id].status = 0
        def cb():
            if self.holds[request_id].status != 0:
                raise AssertionError()
            self.holds[request_id].status = 1
            self.holds.pop(request_id).happened()
        reactor.callLater(dt, cb)

class LongPollingWorkerInterface(deferred_resource.DeferredResource):
    def __init__(self, parent):
        self.parent = parent
    
    @defer.inlineCallbacks
    def render_GET(self, request):
        request.setHeader('Content-Type', 'application/json')
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('X-Roll-NTime', 'expire=60')
        try:
            try:
                request.write(json.dumps({
                    'jsonrpc': '2.0',
                    'id': 0,
                    'result': (yield self.parent.getwork(request, long_poll=True)),
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

class WorkerInterface(jsonrpc.Server):
    def __init__(self, work, compute, response_callback):
        jsonrpc.Server.__init__(self)
        
        self.work = work
        self.compute = compute
        self.response_callback = response_callback
        self.holds = Holds()
        self.last_cache_invalidation = {}
        
        self.putChild('long-polling', LongPollingWorkerInterface(self))
        self.putChild('', self)
    
    @defer.inlineCallbacks
    def rpc_getwork(self, request, data=None):
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('X-Roll-NTime', 'expire=60')
        
        if data is not None:
            defer.returnValue(self.response_callback(getwork.decode_data(data), request))
        
        defer.returnValue((yield self.getwork(request)))
    
    @defer.inlineCallbacks
    def getwork(self, request, long_poll=False):
        request_id = get_id(request)
        memory = get_memory(request)
        
        id = random.randrange(10000)
        if p2pool.DEBUG:
            print 'POLL %i START long_poll=%r user_agent=%r x-work-identifier=%r user=%r' % (id, long_poll, request.getHeader('User-Agent'), request.getHeader('X-Work-Identifier'), get_username(request))
        
        if request_id not in self.last_cache_invalidation:
            self.last_cache_invalidation[request_id] = variable.Variable((None, None))
        
        yield self.holds.wait_hold(request_id)
        work = self.work.value
        thought_work = self.last_cache_invalidation[request_id].value
        
        if long_poll and work == thought_work[-1]:
            if p2pool.DEBUG:
                print 'POLL %i WAITING user=%r' % (id, get_username(request))
            yield defer.DeferredList([self.work.changed.get_deferred(), self.last_cache_invalidation[request_id].changed.get_deferred()], fireOnOneCallback=True)
        work = self.work.value
        
        if thought_work[-1] is not None and work != thought_work[-1] and any(x is None or work['previous_block'] == x['previous_block'] for x in thought_work[-memory or len(thought_work):]):
            # clients won't believe the update
            work = work.copy()
            work['previous_block'] = random.randrange(2**256)
            if p2pool.DEBUG:
                print 'POLL %i FAKED user=%r' % (id, get_username(request))
            self.holds.set_hold(request_id, .01)
        res = self.compute(work, request)
        
        self.last_cache_invalidation[request_id].set((thought_work[-1], work))
        if p2pool.DEBUG:
            print 'POLL %i END %s user=%r' % (id, p2pool_data.format_hash(work['best_share_hash']), get_username(request))
        
        res = res.update(share_target=min(res.share_target, get_max_target(request)))
        
        defer.returnValue(res.getwork(identifier=str(work['best_share_hash'])))
