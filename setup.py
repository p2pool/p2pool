from distutils.core import setup

try:
    import py2exe
except ImportError:
    print "missing py2exe"


setup(name='p2pool',
    version='1.0',
    description='Peer-to-peer Bitcoin mining pool',
    author='Forrest Voight',
    author_email='forrest@forre.st',
    url='http://p2pool.forre.st/',
    
    console=['main.py'],
)
