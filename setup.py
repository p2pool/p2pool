import os
import shutil
import sys
import zipfile
import platform

from distutils.core import setup
from distutils.sysconfig import get_python_lib
import py2exe

version = str('1.4+') + str(__import__('p2pool').__version__)
im64 = '64' in platform.architecture()[0]

extra_includes = []
import p2pool.networks
extra_includes.extend('p2pool.networks.' + x for x in p2pool.networks.nets)
import p2pool.bitcoin.networks
extra_includes.extend('p2pool.bitcoin.networks.' + x for x in p2pool.bitcoin.networks.nets)

if os.path.exists('INITBAK'):
    os.remove('INITBAK')
os.rename(os.path.join('p2pool', '__init__.py'), 'INITBAK')
try:
    open(os.path.join('p2pool', '__init__.py'), 'wb').write('__version__ = %r%s%sDEBUG = False%s' % (version, os.linesep, os.linesep, os.linesep))
    bundle = 1
    if im64:
        bundle = bundle + 2
    sys.argv[1:] = ['py2exe']
    setup(name='p2pool-merged-v36',
        version=version,
        description='Peer-to-peer Litecoin+Dogecoin merged mining pool',
        author='Forrest Voight',
        author_email='forrest@forre.st',
        url='https://github.com/frstrtr/p2pool-merged-v36/',
        data_files=[
            ('', ['README.md']),
            ('web-static', [
                'web-static/d3.v2.min.js',
                'web-static/favicon.ico',
                'web-static/graphs.html',
                'web-static/index.html',
                'web-static/share.html',
                'web-static/dashboard.html',
                'web-static/miner.html',
                'web-static/miners.html',
                'web-static/stratum.html',
                'web-static/highcharts.js',
                'web-static/highcharts-exporting.js',
            ]),
            ('transition_messages', [
                'transition_messages/transition_v35_v36_mainnet.hex',
            ]),
        ],

        console=['run_p2pool.py'],
        options=dict(py2exe=dict(
            bundle_files=bundle,
            dll_excludes=['w9xpopen.exe', "mswsock.dll", "MSWSOCK.dll"],
            includes=['twisted.web.resource',
                      'scrypt',
                      'zope.interface',
                      'win32api',
                     ] + extra_includes,
        )),
        zipfile=None,
    )
finally:
    os.remove(os.path.join('p2pool', '__init__.py'))
    os.rename('INITBAK', os.path.join('p2pool', '__init__.py'))

win = '32'
if im64:
    win = '64'

dir_name = 'p2pool_ltc_win' + win + '_' + version

if os.path.exists(dir_name):
    shutil.rmtree(dir_name)

with zipfile.ZipFile(dir_name + '.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk('dist'):
        for filename in filenames:
            zf.write(os.path.join(dirpath, filename))

try:
    os.rename(dir_name + '.zip', os.path.join('dist', dir_name + '.zip'))
except OSError:  # Windows can't overwrite with rename
    dest = os.path.join('dist', dir_name + '.zip')
    if os.path.exists(dest):
        os.remove(dest)
    os.rename(dir_name + '.zip', dest)

print(dir_name)
