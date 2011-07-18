from __future__ import division

import os
import sqlite3

from p2pool.util import db
from p2pool import p2p

print 'main'
x = p2p.AddrStore(db.SQLiteDict(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'addrs.dat'), isolation_level=None), 'addrs'))

for k, v in x.iteritems():
    print k, v

print
print 'testnet'
x = p2p.AddrStore(db.SQLiteDict(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'addrs.dat'), isolation_level=None), 'addrs_testnet'))

for k, v in x.iteritems():
    print k, v
