from __future__ import division

import base64
import json
import traceback

from twisted.internet import defer
from twisted.web import client

import util

class Error(Exception):
    def __init__(self, code, message, data=None):
        if not isinstance(code, int):
            raise TypeError('code must be an int')
        if not isinstance(message, unicode):
            raise TypeError('message must be a unicode')
        self._code, self._message, self._data = code, message, data
    def __str__(self):
        return '%i %s %r' % (self._code, self._message, self._data)
    def _to_obj(self):
        return {
            'code': self._code,
            'message': self._message,
            'data': self._data,
        }

class Proxy(object):
    def __init__(self, url, auth=None):
        self._url = url
        self._auth = auth
    
    @defer.inlineCallbacks
    def callRemote(self, method, *params):
        id_ = 0
        
        headers = {
            'Content-Type': 'text/json',
        }
        if self._auth is not None:
            headers['Authorization'] = 'Basic ' + base64.b64encode(':'.join(self._auth))
        resp = json.loads((yield client.getPage(
            url=self._url,
            method='POST',
            headers=headers,
            postdata=json.dumps({
                'jsonrpc': '2.0',
                'method': method,
                'params': params,
                'id': id_,
            }),
        )))
        
        if resp['id'] != id_:
            raise ValueError('invalid id')
        if 'error' in resp and resp['error'] is not None:
            raise Error(resp['error'])
        defer.returnValue(resp['result'])
    
    def __getattr__(self, attr):
        if attr.startswith('rpc_'):
            return lambda *params: self.callRemote(attr[len('rpc_'):], *params)
        raise AttributeError('%r object has no attribute %r' % (self.__class__.__name__, attr))

class Server(util.DeferredResource):
    extra_headers = None
    
    @defer.inlineCallbacks
    def render_POST(self, request):
        # missing batching, 1.0 notifications
        data = request.content.read()
        
        if self.extra_headers is not None:
            for name, value in self.extra_headers.iteritems():
                request.setHeader(name, value)
        
        try:
            try:
                req = json.loads(data)
            except Exception:
                raise RemoteError(-32700, u'Parse error')
        except Error, e:
            # id unknown
            request.write(json.dumps({
                'jsonrpc': '2.0',
                'id': None,
                'result': None,
                'error': e._to_obj(),
            }))
        
        id_ = req.get('id', None)
        
        try:
            try:
                method = req['method']
                if not isinstance(method, unicode):
                    raise ValueError()
                params = req.get('params', [])
                if not isinstance(params, list):
                    raise ValueError()
            except Exception:
                raise Error(-32600, u'Invalid Request')
            
            method_name = 'rpc_' + method
            if not hasattr(self, method_name):
                raise Error(-32601, u'Method not found')
            method_meth = getattr(self, method_name)
            
            df = defer.maybeDeferred(method_meth, *params)
            
            if id_ is None:
                return
            
            try:
                result = yield df
            except Error, e:
                raise e
            except Exception, e:
                print 'Squelched JSON method error:'
                traceback.print_exc()
                raise Error(-32099, u'Unknown error')
            
            request.write(json.dumps({
                'jsonrpc': '2.0',
                'id': id_,
                'result': result,
                'error': None,
            }))
        except Error, e:
            request.write(json.dumps({
                'jsonrpc': '2.0',
                'id': id_,
                'result': None,
                'error': e._to_obj(),
            }))
