from __future__ import division

import json

from twisted.internet import defer

from util import jsonrpc, deferred_resource

class LongPollingWorkerInterface(deferred_resource.DeferredResource):
    def __init__(self, work, compute):
        self.work = work
        self.compute = compute
    
    @defer.inlineCallbacks
    def render_GET(self, request):
        request.setHeader('X-Long-Polling', '/long-polling')
        
        res = self.compute((yield self.work.changed.get_deferred()), 'x-all-targets' in map(str.lower, request.received_headers))
        
        request.setHeader('Content-Type', 'application/json')
        request.write(json.dumps({
            'jsonrpc': '2.0',
            'id': 0,
            'result': res,
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
    extra_headers = {
        'X-Long-Polling': '/long-polling',
    }
    
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
    
    def rpc_getwork(self, headers, data=None):
        if data is not None:
            return self.response_callback(data)
        
        return self.compute(self.work.value, 'x-all-targets' in map(str.lower, headers))
    rpc_getwork.takes_headers = True
