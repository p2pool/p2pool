import os
import subprocess
import sys

subprocess.check_call(['git', 'checkout', 'p2pool/__init__.py'])
version = __import__('p2pool').__version__
open('p2pool/__init__.py', 'wb').write('__version__ = %r%s%sDEBUG = False%s' % (version, os.linesep, os.linesep, os.linesep))

from distutils.core import setup
import py2exe

sys.argv[1:] = ['py2exe']
setup(name='p2pool',
    version=version,
    description='Peer-to-peer Bitcoin mining pool',
    author='Forrest Voight',
    author_email='forrest@forre.st',
    url='http://p2pool.forre.st/',
    data_files=[('', ['README'])],
    
    console=['run_p2pool.py'],
    options=dict(py2exe=dict(
        bundle_files=1,
        dll_excludes=['w9xpopen.exe'],
        includes=['twisted.web.resource', 'ltc_scrypt'],
    )),
    zipfile=None,
)

dir_name = 'p2pool_win32_' + version
print dir_name
os.rename('dist', dir_name)
