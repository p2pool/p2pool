import os
import sys
import traceback
import subprocess

def _get_version():
    try:
        return subprocess.check_output(['git', 'describe', '--always', '--dirty'], cwd=os.path.dirname(sys.argv[0])).strip()
    except:
        pass
    try:
        root_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
        git_dir = os.path.join(root_dir, '.git')
        if os.path.exists(git_dir):
            head = open(os.path.join(git_dir, 'HEAD')).read().strip()
            prefix = 'ref: '
            if head.startswith(prefix):
                path = head[len(prefix):].split('/')
                return open(os.path.join(git_dir, *path)).read().strip()[:7]
            else:
                return head[:7]
        dir_name = os.path.split(root_dir)[1]
        chars = '0123456789abcdef'
        if len(dir_name) >= 7 and (len(dir_name) == 7 or dir_name[-8] not in chars) and all(c in chars for c in dir_name[-7:]):
            return dir_name[-7:]
    except Exception, e:
        traceback.print_exc()
    return 'unknown'

__version__ = _get_version()

DEBUG = False
