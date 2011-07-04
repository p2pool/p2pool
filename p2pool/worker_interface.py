from __future__ import division

import json
import traceback

from twisted.internet import defer

from util import jsonrpc, deferred_resource

class LongPollingWorkerInterface(deferred_resource.DeferredResource):
    def __init__(self, work, compute):
        self.work = work
        self.compute = compute
    
    @defer.inlineCallbacks
    def render_GET(self, request):
        request.setHeader('X-Long-Polling', '/long-polling')
        
        res = self.compute((yield self.work.changed.get_deferred()))
        
        request.write(json.dumps({
            'jsonrpc': '2.0',
            'id': 0,
            'result': res,
            'error': None,
        }))
    render_POST = render_GET

class WorkerInterface(jsonrpc.Server):
    extra_headers = {
        'X-Long-Polling': '/long-polling',
    }
    
    def __init__(self, work, compute, response_callback):
        jsonrpc.Server.__init__(self)
        
        self.work = work
        self.compute = compute
        self.response_callback = response_callback
        
        self.putChild('long-polling',
            LongPollingWorkerInterface(self.work, self.compute))
        self.putChild('', self)
    
    def rpc_getwork(self, data=None):
      try:
        if data is not None:
            return self.response_callback(data)
        
        return self.compute(self.work.value)
      except ValueError:
        traceback.print_exc()
