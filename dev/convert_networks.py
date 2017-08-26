import sys

f = open(sys.argv[1])

while True:
    if f.readline().strip() == 'nets = dict(': break

def nesting(l):
    res = 0
    for c in l:
        if c == '(': res += 1
        if c == ')': res -= 1
    return res

def write_header(f, name):
    if sys.argv[3] == 'p2pool':
        f2.write('from p2pool.bitcoin import networks\n\n')
        if name == 'bitcoin':
            f2.write('''# CHAIN_LENGTH = number of shares back client keeps
# REAL_CHAIN_LENGTH = maximum number of shares back client uses to compute payout
# REAL_CHAIN_LENGTH must always be <= CHAIN_LENGTH
# REAL_CHAIN_LENGTH must be changed in sync with all other clients
# changes can be done by changing one, then the other

''')
    elif sys.argv[3] == 'bitcoin':
        f2.write('''import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


''')
    else: assert False, 'invalid type argument'

while True:
    l = f.readline()
    if not l.strip(): continue
    if l.strip() == ')': break
    
    name = l.strip().split('=')[0]

    lines = []
    while True:
        l = f.readline()
        if not l.strip(): continue
        if l.strip() == '),': break
        while nesting(l) != 0:
            l += f.readline()
        lines.append(l.split('=', 1))
    with open(sys.argv[2] + name + '.py', 'wb') as f2:
        write_header(f2, name)
        for a, b in lines:
            if ', #' in b: b = b.replace(', #', ' #')
            elif b.strip().endswith(','): b = b.strip()[:-1]
            else: assert False, b
            f2.write('%s = %s\n' % (a.strip(), b.strip()))
