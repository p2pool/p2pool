from __future__ import division

import json
import random

from twisted.internet import defer

from p2pool.bitcoin import getwork
from p2pool.util import jsonrpc, deferred_resource


class LongPollingWorkerInterface(deferred_resource.DeferredResource):
    def __init__(self, work, compute):
        self.work = work
        self.compute = compute
    
    @defer.inlineCallbacks
    def render_GET(self, request):
        res = self.compute((yield self.work.changed.get_deferred()), request.getHeader('X-All-Targets') is not None)
        
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('Content-Type', 'application/json')
        request.write(json.dumps({
            'jsonrpc': '2.0',
            'id': 0,
            'result': res.getwork(),
            'error': None,
        }))
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
        
        res = self.compute(self.work.value, request.getHeader('X-All-Targets') is not None)
        
        return res.getwork()
    rpc_getwork.takes_request = True
