import os
import sys
import subprocess

prev = os.getcwd()
os.chdir(os.path.abspath(os.path.dirname(sys.argv[0])))
try:
    __version__ = subprocess.Popen(['git', 'describe', '--always'], stdout=subprocess.PIPE).stdout.read().strip()
except:
    __version__ = 'unknown'
os.chdir(prev)

DEBUG = False
