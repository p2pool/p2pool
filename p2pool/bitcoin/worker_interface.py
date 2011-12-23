from __future__ import division

import base64
import random

from twisted.internet import defer

import p2pool
from p2pool import data as p2pool_data
from p2pool.util import jsonrpc, variable
from p2pool.bitcoin import getwork

def get_username(request):
    try:
        return base64.b64decode(request.getHeader('Authorization').split(' ', 1)[1]).split(':')[0]
    except: # XXX
        return None

def get_id(request):
    return request.getClientIP(), request.getHeader('Authorization')

class LongPollingWorkerInterface(jsonrpc.Server):
    def __init__(self, parent):
        jsonrpc.Server.__init__(self)
        self.parent = parent
    
    def rpc_getwork(self, request, data=None):
        return self.parent.getwork(request, data, long_poll=True)

class WorkerInterface(jsonrpc.Server):
    def __init__(self, compute, response_callback, new_work_event=variable.Event()):
        jsonrpc.Server.__init__(self)
        
        self.compute = compute
        self.response_callback = response_callback
        self.new_work_event = new_work_event
        
        self.worker_views = {}
        
        self.putChild('long-polling', LongPollingWorkerInterface(self))
        self.putChild('', self)
    
    def rpc_getwork(self, request, data=None):
        return self.getwork(request, data, long_poll=False)
    
    @defer.inlineCallbacks
    def getwork(self, request, data, long_poll):
        request.setHeader('X-Long-Polling', '/long-polling')
        request.setHeader('X-Roll-NTime', 'expire=60')
        
        if data is not None:
            defer.returnValue(self.response_callback(getwork.decode_data(data), request))
        
        request_id = get_id(request)
        
        if p2pool.DEBUG:
            id = random.randrange(1000, 10000)
            print 'POLL %i START long_poll=%r user_agent=%r x-work-identifier=%r user=%r' % (id, long_poll, request.getHeader('User-Agent'), request.getHeader('X-Work-Identifier'), get_username(request))
        
        if request_id not in self.worker_views:
            self.worker_views[request_id] = variable.Variable(None)
        
        if long_poll and self.worker_views[request_id].value in [None, self.new_work_event.times]:
            if p2pool.DEBUG:
                print 'POLL %i WAITING user=%r' % (id, get_username(request))
            yield self.new_work_event.get_deferred()
        
        res, identifier = self.compute(request)
        
        if long_poll:
            self.worker_views[request_id].set(self.new_work_event.times)
        
        if p2pool.DEBUG:
            print 'POLL %i END %s user=%r' % (id, p2pool_data.format_hash(identifier), get_username(request)) # XXX identifier is hack
        
        defer.returnValue(res.getwork(identifier=str(identifier)))
