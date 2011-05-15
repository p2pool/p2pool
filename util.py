from twisted.internet import defer
from twisted.web import server, resource

class DeferredResource(resource.Resource):
    def render(self, request): 
        def finish(x):
            if x is not None:
                request.write(x)
            request.finish()
        def finish_error(x):
            request.setResponseCode(500) # won't do anything if already written to
            request.write("---ERROR---")
            request.finish()
            return x # prints traceback
        defer.maybeDeferred(resource.Resource.render, self, request).addCallbacks(finish, finish_error)
        return server.NOT_DONE_YET
