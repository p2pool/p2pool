from twisted.internet import defer

import jsonrpc
import util
import json

class LongPollingWorkerInterface(util.DeferredResource):
    def __init__(self, work):
        self.work = work
    @defer.inlineCallbacks
    def render_POST(self, request):
        request.write(json.dumps((yield self.work.get_deferred())))
    render_GET = render_POST

class WorkerInterface(jsonrpc.Server):
    extra_headers = {
        'X-Long-Polling': '/long-polling',
    }
    
    def __init__(self, work, response_callback):
        jsonrpc.Server.__init__(self)
        
        self.work = work
        self.response_callback = response_callback
        
        self.putChild('long-polling', LongPollingWorkerInterface(self.work))
        self.putChild('', self)
    
    @defer.inlineCallbacks
    def rpc_getwork(self, data=None):
        if data is not None:
            defer.returnValue(self.response_callback(data))
        
        work = self.work.get()
        
        if work is None:
            defer
        
        defer.returnValue(work)
