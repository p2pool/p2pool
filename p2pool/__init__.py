import os
import sys

def _get_version():
    try:
        git_dir = os.path.join(os.path.abspath(os.path.dirname(sys.argv[0])), '.git')
        head = open(os.path.join(git_dir, 'HEAD')).read().strip()
        prefix = 'ref: '
        if head.startswith(prefix):
            path = head[len(prefix):].split('/')
            return open(os.path.join(git_dir, *path)).read().strip()
        else:
            return head
    except Exception, e:
        return 'unknown (%s)' % (str(e),)

__version__ = _get_version()

DEBUG = False
