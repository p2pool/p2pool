import os
import sys

from distutils.core import setup
import py2exe

def get_version():
    root_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
    git_dir = os.path.join(root_dir, '.git')
    head = open(os.path.join(git_dir, 'HEAD')).read().strip()
    prefix = 'ref: '
    if head.startswith(prefix):
        path = head[len(prefix):].split('/')
        return open(os.path.join(git_dir, *path)).read().strip()[:7]
    else:
        return head[:7]

open('p2pool/__init__.py', 'wb').write('__version__ = %r\r\n\r\nDEBUG = False\r\n' % get_version())

sys.argv[1:] = ['py2exe']
setup(name='p2pool',
    version='1.0',
    description='Peer-to-peer Bitcoin mining pool',
    author='Forrest Voight',
    author_email='forrest@forre.st',
    url='http://p2pool.forre.st/',
    data_files=[('', ['README', 'README-Litecoin'])],
    
    console=['run_p2pool.py'],
    options=dict(py2exe=dict(
        bundle_files=1,
        dll_excludes=['w9xpopen.exe'],
        includes=['twisted.web.resource', 'ltc_scrypt'],
    )),
    zipfile=None,
)

os.rename('dist', 'p2pool_win32_' + get_version())
print 'p2pool_win32_' + get_version()