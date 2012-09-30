from __future__ import division

from twisted.internet import defer
from twisted.web import resource, server
from twisted.python import log

class DeferredResource(resource.Resource):
    def render(self, request):
        def finish(x):
            if request.channel is None: # disconnected
                return
            if x is not None:
                request.write(x)
            request.finish()
        
        def finish_error(fail):
            if request.channel is None: # disconnected
                return
            request.setResponseCode(500) # won't do anything if already written to
            request.write('---ERROR---')
            request.finish()
            log.err(fail, "Error in DeferredResource handler:")
        
        defer.maybeDeferred(resource.Resource.render, self, request).addCallbacks(finish, finish_error)
        return server.NOT_DONE_YET
