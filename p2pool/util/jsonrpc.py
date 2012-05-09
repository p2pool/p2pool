from __future__ import division

import json

from twisted.internet import defer
from twisted.python import log
from twisted.web import client, error

import deferred_resource

class Error(Exception):
    def __init__(self, code, message, data=None):
        if not isinstance(code, int):
            raise TypeError('code must be an int')
        #if not isinstance(message, unicode):
        #    raise TypeError('message must be a unicode')
        self.code, self.message, self.data = code, message, data
    def __str__(self):
        return '%i %s' % (self.code, self.message) + (' %r' % (self.data, ) if self.data is not None else '')
    def _to_obj(self):
        return {
            'code': self.code,
            'message': self.message,
            'data': self.data,
        }

class Proxy(object):
    def __init__(self, url, headers={}, timeout=5):
        self._url = url
        self._headers = headers
        self._timeout = timeout
    
    @defer.inlineCallbacks
    def callRemote(self, method, *params):
        id_ = 0
        
        try:
            data = yield client.getPage(
                url=self._url,
                method='POST',
                headers=dict(self._headers, **{'Content-Type': 'application/json'}),
                postdata=json.dumps({
                    'jsonrpc': '2.0',
                    'method': method,
                    'params': params,
                    'id': id_,
                }),
                timeout=self._timeout,
            )
        except error.Error, e:
            try:
                resp = json.loads(e.response)
            except:
                raise e
        else:
            resp = json.loads(data)
        
        if resp['id'] != id_:
            raise ValueError('invalid id')
        if 'error' in resp and resp['error'] is not None:
            raise Error(**resp['error'])
        defer.returnValue(resp['result'])
    
    def __getattr__(self, attr):
        if attr.startswith('rpc_'):
            return lambda *params: self.callRemote(attr[len('rpc_'):], *params)
        raise AttributeError('%r object has no attribute %r' % (self.__class__.__name__, attr))

class Server(deferred_resource.DeferredResource):
    def __init__(self, provider):
        deferred_resource.DeferredResource.__init__(self)
        self._provider = provider
    
    @defer.inlineCallbacks
    def render_POST(self, request):
        id_ = None
        
        try:
            try:
                data = request.content.read()
                
                try:
                    req = json.loads(data)
                except Exception:
                    raise Error(-32700, u'Parse error')
                
                id_ = req.get('id', None)
                method = req.get('method', None)
                if not isinstance(method, basestring):
                    raise Error(-32600, u'Invalid Request')
                params = req.get('params', [])
                if not isinstance(params, list):
                    raise Error(-32600, u'Invalid Request')
                
                method_meth = getattr(self._provider, 'rpc_' + method, None)
                if method_meth is None:
                    raise Error(-32601, u'Method not found')
                
                result = yield method_meth(request, *params)
                error = None
            except Error:
                raise
            except Exception:
                log.err(None, 'Squelched JSON error:')
                raise Error(-32099, u'Unknown error')
        except Error, e:
            result = None
            error = e._to_obj()
        
        data = json.dumps(dict(
            jsonrpc='2.0',
            id=id_,
            result=result,
            error=error,
        ))
        request.setHeader('Content-Type', 'application/json')
        request.setHeader('Content-Length', len(data))
        request.write(data)
