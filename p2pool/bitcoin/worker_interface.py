from __future__ import division

import StringIO
import json
import random
import sys

from twisted.internet import defer

import p2pool
from p2pool.bitcoin import data as bitcoin_data, getwork
from p2pool.util import expiring_dict, jsonrpc, pack, variable

class _Provider(object):
    def __init__(self, parent, long_poll):
        self.parent = parent
        self.long_poll = long_poll
    
    def rpc_getwork(self, request, data=None):
        return self.parent._getwork(request, data, long_poll=self.long_poll)

class _GETableServer(jsonrpc.HTTPServer):
    def __init__(self, provider, render_get_func):
        jsonrpc.HTTPServer.__init__(self, provider)
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
        
        self.merkle_root_to_handler = expiring_dict.ExpiringDict(300)
    
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
        request.setHeader('X-Roll-NTime', 'expire=100')
        request.setHeader('X-Is-P2Pool', 'true')
        if request.getHeader('Host') is not None:
            request.setHeader('X-Stratum', 'stratum+tcp://' + request.getHeader('Host'))
        
        if data is not None:
            header = getwork.decode_data(data)
            if header['merkle_root'] not in self.merkle_root_to_handler:
                print >>sys.stderr, '''Couldn't link returned work's merkle root with its handler. This should only happen if this process was recently restarted!'''
                defer.returnValue(False)
            defer.returnValue(self.merkle_root_to_handler[header['merkle_root']](header, request.getUser() if request.getUser() is not None else '', '\0'*self.worker_bridge.COINBASE_NONCE_LENGTH))
        
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
        
        x, handler = self.worker_bridge.get_work(*self.worker_bridge.preprocess_request(request.getUser() if request.getUser() is not None else ''))
        res = getwork.BlockAttempt(
            version=x['version'],
            previous_block=x['previous_block'],
            merkle_root=bitcoin_data.check_merkle_link(bitcoin_data.hash256(x['coinb1'] + '\0'*self.worker_bridge.COINBASE_NONCE_LENGTH + x['coinb2']), x['merkle_link']),
            timestamp=x['timestamp'],
            bits=x['bits'],
            share_target=x['share_target'],
        )
        assert res.merkle_root not in self.merkle_root_to_handler
        
        self.merkle_root_to_handler[res.merkle_root] = handler
        
        if p2pool.DEBUG:
            print 'POLL %i END identifier=%i' % (id, self.worker_bridge.new_work_event.times)
        
        extra_params = {}
        if request.getHeader('User-Agent') == 'Jephis PIC Miner':
            # ASICMINER BE Blades apparently have a buffer overflow bug and
            # can't handle much extra in the getwork response
            extra_params = {}
        else:
            extra_params = dict(identifier=str(self.worker_bridge.new_work_event.times), submitold=True)
        defer.returnValue(res.getwork(**extra_params))

class CachingWorkerBridge(object):
    def __init__(self, inner):
        self._inner = inner
        self.net = self._inner.net
        
        self.COINBASE_NONCE_LENGTH = (inner.COINBASE_NONCE_LENGTH+1)//2
        self.new_work_event = inner.new_work_event
        self.preprocess_request = inner.preprocess_request
        
        self._my_bits = (self._inner.COINBASE_NONCE_LENGTH - self.COINBASE_NONCE_LENGTH)*8
        
        self._cache = {}
        self._times = None
    
    def get_work(self, *args):
        if self._times != self.new_work_event.times:
            self._cache = {}
            self._times = self.new_work_event.times
        
        if args not in self._cache:
            x, handler = self._inner.get_work(*args)
            self._cache[args] = x, handler, 0
        
        x, handler, nonce = self._cache.pop(args)
        
        res = (
            dict(x, coinb1=x['coinb1'] + pack.IntType(self._my_bits).pack(nonce)),
            lambda header, user, coinbase_nonce: handler(header, user, pack.IntType(self._my_bits).pack(nonce) + coinbase_nonce),
        )
        
        if nonce + 1 != 2**self._my_bits:
            self._cache[args] = x, handler, nonce + 1
        
        return res
