import os
import shutil
import sys
import zipfile

from distutils.core import setup
import py2exe

version = __import__('p2pool').__version__

if os.path.exists('INITBAK'):
    os.remove('INITBAK')
os.rename(os.path.join('p2pool', '__init__.py'), 'INITBAK')
try:
    open(os.path.join('p2pool', '__init__.py'), 'wb').write('__version__ = %r%s%sDEBUG = False%s' % (version, os.linesep, os.linesep, os.linesep))
    
    sys.argv[1:] = ['py2exe']
    setup(name='p2pool',
        version=version,
        description='Peer-to-peer Bitcoin mining pool',
        author='Forrest Voight',
        author_email='forrest@forre.st',
        url='http://p2pool.forre.st/',
        data_files=[
            ('', ['README']),
            ('web-static', [
                'web-static/d3.v2.min.js',
                'web-static/graphs.html',
                'web-static/index.html',
            ]),
        ],
        
        console=['run_p2pool.py'],
        options=dict(py2exe=dict(
            bundle_files=1,
            dll_excludes=['w9xpopen.exe'],
            includes=['twisted.web.resource', 'ltc_scrypt'],
        )),
        zipfile=None,
    )
finally:
    os.remove(os.path.join('p2pool', '__init__.py'))
    os.rename('INITBAK', os.path.join('p2pool', '__init__.py'))

dir_name = 'p2pool_win32_' + version

if os.path.exists(dir_name):
    shutil.rmtree(dir_name)
os.rename('dist', dir_name)

with zipfile.ZipFile(dir_name + '.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk(dir_name):
        for filename in filenames:
            zf.write(os.path.join(dirpath, filename))

print dir_name
