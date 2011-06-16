from __future__ import division

class SQLiteDict(object):
    def __init__(self, db, table):
        self._db = db
        self._table = table
        
        self._db.execute('CREATE TABLE IF NOT EXISTS %s(key BLOB PRIMARY KEY NOT NULL, value BLOB NOT NULL)' % (self._table,))
    
    def __len__(self):
        for row in self._db.execute('SELECT COUNT(key) FROM %s' % (self._table,)):
            return row[0]
    
    def __iter__(self):
        for row in self._db.execute('SELECT key FROM %s' % (self._table,)):
            yield str(row[0])
    def iterkeys(self):
        return iter(self)
    def keys(self):
        return list(self)
    
    def itervalues(self):
        for row in self._db.execute('SELECT value FROM %s' % (self._table,)):
            yield str(row[0])
    def values(self):
        return list(self.itervalues)
    
    def iteritems(self):
        for row in self._db.execute('SELECT key, value FROM %s' % (self._table,)):
            yield (str(row[0]), str(row[1]))
    def items(self):
        return list(self.iteritems())
    
    def __setitem__(self, key, value):
        if self._db.execute('SELECT key FROM %s where key=?' % (self._table,), (buffer(key),)).fetchone() is None:
            self._db.execute('INSERT INTO %s (key, value) VALUES (?, ?)' % (self._table,), (buffer(key), buffer(value)))
        else:
            self._db.execute('UPDATE %s SET value=? WHERE key=?' % (self._table,), (buffer(value), buffer(key)))
    
    def __getitem__(self, key):
        row = self._db.execute('SELECT value FROM %s WHERE key=?' % (self._table,), (buffer(key),)).fetchone()
        if row is None:
            raise KeyError(key)
        else:
            return str(row[0])
    
    def __delitem__(self, key):
        self._db.execute('DELETE FROM %s WHERE key=?' % (self._table,), (buffer(key),))
