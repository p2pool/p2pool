import time

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
            raise ValueError("node already connected")
        prev.next, next.prev = next, prev

    def replace(self, contents):
        self.contents = contents

    def delete(self):
       if self.prev.next is None or self.next.prev is None:
            raise ValueError("node not connected")
       self.prev.next, self.next.prev = self.next, self.prev
       self.next = self.prev = None


class LinkedList(object):
    def __init__(self, iterable=[]):
        self.start, self.end = Node(None), Node(None)
        Node.connect(self.start, self.end)
        
        for item in iterable:
            self.append(item)
    
    def __repr__(self):
        return "LinkedList(%r)" % (list(self),)
    
    def __iter__(self):
        cur = self.start.next
        while True:
            if cur is self.end:
                break
            yield cur.contents
            cur = cur.next
    
    def __len__(self):
        return sum(1 for x in self)

    def __reversed__(self):
        cur = self.end.prev
        while True:
            if cur is self.start:
                break
            cur = cur.prev
            yield cur.contents
    
    def __getitem__(self, index):
        if index < 0:
            cur = self.end
            for i in xrange(-index):
                cur = cur.prev
                if cur is self.start:
                    raise IndexError("index out of range")
        else:
            cur = self.start
            for i in xrange(index + 1):
                cur = cur.next
                if cur is self.end:
                    raise IndexError("index out of range")
        return cur.contents
    
    def appendleft(self, item):
        return self.start.insert_after(item)
    
    def append(self, item):
        return self.end.insert_before(item)
    
    def popleft(self):
        node = self.start.next
        if node is self.end:
            raise IndexError("popleft from empty")
        node.delete()
        return node.contents
    
    def pop(self):
        node = self.end.prev
        if node is self.start:
            raise IndexError("pop from empty")
        node.delete()
        return node.contents


class ExpiringDict(object):
    def __init__(self, expiry_time=600):
        self.d = dict()
        self.expiry_time = expiry_time
        self.expiry_deque = LinkedList()
        self.key_to_node = {}
    
    def __repr__(self):
        self._expire()
        return "ExpiringDict" + repr(self.__dict__)
    
    def _touch(self, key):
        if key in self.key_to_node:
            self.key_to_node[key].delete()
        self.key_to_node[key] = self.expiry_deque.append((time.time(), key))
    
    def _expire(self):
        while self.expiry_deque and self.expiry_deque[0][0] < time.time() - self.expiry_time:
            timestamp, key = self.expiry_deque.popleft()
            del self.d[key]
            del self.key_to_node[key]
    
    def __getitem__(self, key):
        value = self.d[key]
        self._touch(key)
        self._expire()
        return value
    
    def __setitem__(self, key, value):
        self.d[key] = value
        self._touch(key)
        self._expire()
    
    def __delitem__(self, key):
        del self.d[key]
        self.key_to_node.pop(key).delete()
        self._expire()
    
    def get(self, key, default_value):
        if key in self.d:
            return self[key]
        else:
            return default_value
    
    def setdefault(self, key, default_value):
        value = self.d.get(key, default_value)
        self[key] = value
        return value

if __name__ == '__main__':
    x = ExpiringDict(5)
    print x
    
    time.sleep(1)
    
    x[1] = 2
    print "x[1] = 2"
    print x
    
    time.sleep(1)
    
    x[1] = 3
    print "x[1] = 3"
    print x
    
    time.sleep(5)
    
    print x
