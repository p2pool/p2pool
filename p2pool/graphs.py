import os
import tempfile

from twisted.web import resource

try:
    import rrdtool
except ImportError:
    class Resource(resource.Resource):
        def __init__(self):
            resource.Resource.__init__(self)
            
            self.putChild('', self)
        
        def render_GET(self, request):
            if not request.path.endswith('/'):
                request.redirect(request.path + '/')
                return ''
            request.setHeader('Content-Type', 'text/html')
            return '<html><head><title>P2Pool Graphs</title></head><body><p>Install python-rrdtool!</p></body></html>'
    
    class Grapher(object):
        def __init__(self, *args): pass
        def add_poolrate_point(self, *args): pass
        def add_localrate_point(self, *args): pass
        def get_resource(self): return Resource()
else:
    class Renderer(resource.Resource):
        def __init__(self, *args):
            self.args = args
        
        def render_GET(self, request):
            handle, filename = tempfile.mkstemp()
            os.close(handle)
            
            rrdtool.graph(filename, '--imgformat', 'PNG', *self.args)
            
            request.setHeader('Content-Type', 'image/png')
            return open(filename, 'rb').read()
    
    class Resource(resource.Resource):
        def __init__(self, grapher):
            resource.Resource.__init__(self)
            self.grapher = grapher
            
            self.putChild('', self)
            
            self.putChild('poolrate_day', Renderer('--lower-limit', '0', '--start', '-1d',
                'DEF:A=%s.poolrate:poolrate:AVERAGE' % (self.grapher.path,), 'LINE1:A#0000FF:Total (last day)',
                'DEF:B=%s.localrate:localrate:AVERAGE' % (self.grapher.path,), 'LINE1:B#0000FF:Local (last day)'))
            self.putChild('poolrate_week', Renderer('--lower-limit', '0', '--start', '-1w',
                'DEF:A=%s.poolrate:poolrate:AVERAGE' % (self.grapher.path,), 'LINE1:A#0000FF:Total (last week)',
                'DEF:B=%s.localrate:localrate:AVERAGE' % (self.grapher.path,), 'LINE1:B#0000FF:Local (last week)'))
            self.putChild('poolrate_month', Renderer('--lower-limit', '0', '--start', '-1m',
                'DEF:A=%s.poolrate:poolrate:AVERAGE' % (self.grapher.path,), 'LINE1:A#0000FF:Total (last month)',
                'DEF:B=%s.localrate:localrate:AVERAGE' % (self.grapher.path,), 'LINE1:B#0000FF:Local (last month)'))
            
            self.putChild('localrate_day', Renderer('--lower-limit', '0', '--start', '-1d',
                'DEF:A=%s.localrate:localrate:AVERAGE' % (self.grapher.path,), 'LINE1:A#0000FF:Total (last day)',
                'DEF:B=%s.localdeadrate:localdeadrate:AVERAGE' % (self.grapher.path,), 'LINE1:B#FF0000:Dead (last day)'))
            self.putChild('localrate_week', Renderer('--lower-limit', '0', '--start', '-1w',
                'DEF:A=%s.localrate:localrate:AVERAGE' % (self.grapher.path,), 'LINE1:A#0000FF:Total (last week)',
                'DEF:B=%s.localdeadrate:localdeadrate:AVERAGE' % (self.grapher.path,), 'LINE1:B#FF0000:Dead (last week)'))
            self.putChild('localrate_month', Renderer('--lower-limit', '0', '--start', '-1m',
                'DEF:A=%s.localrate:localrate:AVERAGE' % (self.grapher.path,), 'LINE1:A#0000FF:Total (last month)',
                'DEF:B=%s.localdeadrate:localdeadrate:AVERAGE' % (self.grapher.path,), 'LINE1:B#FF0000:Dead (last month)'))
        
        def render_GET(self, request):
            if not request.path.endswith('/'):
                request.redirect(request.path + '/')
                return ''
            request.setHeader('Content-Type', 'text/html')
            return '''<html><head><title>P2Pool Graphs</title></head><body><h1>P2Pool Graphs</h1>
                <h2>Pool hash rate:</h2>
                <p><img style="display:inline" src="poolrate_day"/> <img style="display:inline" src="poolrate_week"/> <img style="display:inline" src="poolrate_month"/></p>
                <h2>Local hash rate:</h2>
                <p><img style="display:inline" src="localrate_day"/> <img style="display:inline" src="localrate_week"/> <img style="display:inline" src="localrate_month"/></p>
            </body></html>'''
    
    class Grapher(object):
        def __init__(self, path):
            self.path = path
            
            if not os.path.exists(self.path + '.poolrate'):
                rrdtool.create(self.path + '.poolrate', '--step', '300', '--no-overwrite',
                    'DS:poolrate:GAUGE:600:U:U',
                    'RRA:AVERAGE:0.5:1:288', # last day
                    'RRA:AVERAGE:0.5:7:288', # last week
                    'RRA:AVERAGE:0.5:30:288', # last month
                )
            if not os.path.exists(self.path + '.localrate'):
                rrdtool.create(self.path + '.localrate', '--step', '300', '--no-overwrite',
                    'DS:localrate:ABSOLUTE:43200:U:U',
                    'RRA:AVERAGE:0.5:1:288', # last day
                    'RRA:AVERAGE:0.5:7:288', # last week
                    'RRA:AVERAGE:0.5:30:288', # last month
                )
            if not os.path.exists(self.path + '.localdeadrate'):
                rrdtool.create(self.path + '.localdeadrate', '--step', '300', '--no-overwrite',
                    'DS:localdeadrate:ABSOLUTE:43200:U:U',
                    'RRA:AVERAGE:0.5:1:288', # last day
                    'RRA:AVERAGE:0.5:7:288', # last week
                    'RRA:AVERAGE:0.5:30:288', # last month
                )
        
        def add_poolrate_point(self, poolrate):
            rrdtool.update(self.path + '.poolrate', '-t', 'poolrate', 'N:%f' % (poolrate,))
        
        def add_localrate_point(self, hashes, dead):
            rrdtool.update(self.path + '.localrate', '-t', 'localrate', 'N:%f' % (hashes,))
            rrdtool.update(self.path + '.localdeadrate', '-t', 'localdeadrate', 'N:%f' % (hashes if dead else 0,))
        
        def get_resource(self):
            return Resource(self)
