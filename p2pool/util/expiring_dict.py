from __future__ import division

import time
import weakref

from p2pool.util import deferral

class Node(object):
    def __init__(self, contents, prev=None, next=None):
        self.contents, self.prev, self.next = contents, prev, next
    
    def insert_before(self, contents):
        self.prev.next = self.prev = node = Node(contents, self.prev, self)
        return node
    
    def insert_after(self, contents):
        self.next.prev = self.next = node = Node(contents, self, self.next)
        return node
    
    @staticmethod
    def connect(prev, next):
        if prev.next is not None or next.prev is not None:
            raise ValueError('node already connected')
        prev.next, next.prev = next, prev
    
    def replace(self, contents):
        self.contents = contents
    
    def delete(self):
        if self.prev.next is None or self.next.prev is None:
            raise ValueError('node not connected')
        self.prev.next, self.next.prev = self.next, self.prev
        self.next = self.prev = None


class LinkedList(object):
    def __init__(self, iterable=[]):
        self.start, self.end = Node(None), Node(None)
        Node.connect(self.start, self.end)
        
        for item in iterable:
            self.append(item)
    
    def __repr__(self):
        return 'LinkedList(%r)' % (list(self),)
    
    def __len__(self):
        return sum(1 for x in self)
    
    def __iter__(self):
        cur = self.start.next
        while cur is not self.end:
            cur2 = cur
            cur = cur.next
            yield cur2 # in case cur is deleted, but items inserted after are ignored
    
    def __reversed__(self):
        cur = self.end.prev
        while cur is not self.start:
            cur2 = cur
            cur = cur.prev
            yield cur2
    
    def __getitem__(self, index):
        if index < 0:
            cur = self.end
            for i in xrange(-index):
                cur = cur.prev
                if cur is self.start:
                    raise IndexError('index out of range')
        else:
            cur = self.start
            for i in xrange(index + 1):
                cur = cur.next
                if cur is self.end:
                    raise IndexError('index out of range')
        return cur
    
    def appendleft(self, item):
        return self.start.insert_after(item)
    
    def append(self, item):
        return self.end.insert_before(item)
    
    def popleft(self):
        node = self.start.next
        if node is self.end:
            raise IndexError('popleft from empty')
        node.delete()
        return node.contents
    
    def pop(self):
        node = self.end.prev
        if node is self.start:
            raise IndexError('pop from empty')
        node.delete()
        return node.contents


class ExpiringDict(object):
    def __init__(self, expiry_time, get_touches=True):
        self.expiry_time = expiry_time
        self.get_touches = get_touches
        
        self.expiry_deque = LinkedList()
        self.d = dict() # key -> node, value
        
        self_ref = weakref.ref(self, lambda _: expire_loop.stop() if expire_loop.running else None)
        self._expire_loop = expire_loop = deferral.RobustLoopingCall(lambda: self_ref().expire())
        expire_loop.start(1)
    
    def stop(self):
        self._expire_loop.stop()
    
    def __repr__(self):
        return 'ExpiringDict' + repr(self.__dict__)
    
    def __len__(self):
        return len(self.d)
    
    _nothing = object()
    def touch(self, key, value=_nothing):
        'Updates expiry node, optionally replacing value, returning new value'
        if value is self._nothing or key in self.d:
            node, old_value = self.d[key]
            node.delete()
        
        new_value = old_value if value is self._nothing else value
        self.d[key] = self.expiry_deque.append((time.time() + self.expiry_time, key)), new_value
        return new_value
    
    def expire(self):
        t = time.time()
        for node in self.expiry_deque:
            timestamp, key = node.contents
            if timestamp > t:
                break
            del self.d[key]
            node.delete()
    
    def __contains__(self, key):
        return key in self.d
    
    def __getitem__(self, key):
        if self.get_touches:
            value = self.touch(key)
        else:
            node, value = self.d[key]
        return value
    
    def __setitem__(self, key, value):
        self.touch(key, value)
    
    def __delitem__(self, key):
        node, value = self.d.pop(key)
        node.delete()
    
    def get(self, key, default_value=None):
        if key in self.d:
            res = self[key]
        else:
            res = default_value
        return res
    
    def setdefault(self, key, default_value):
        if key in self.d:
            return self[key]
        else:
            self[key] = default_value
            return default_value
    
    def keys(self):
        return self.d.keys()
    
    def values(self):
        return [value for node, value in self.d.itervalues()]
    
    def itervalues(self):
        for node, value in self.d.itervalues():
            yield value
