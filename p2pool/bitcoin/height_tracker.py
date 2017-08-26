from twisted.internet import defer
from twisted.python import log

import p2pool
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, forest, jsonrpc, variable

class HeaderWrapper(object):
    __slots__ = 'hash previous_hash'.split(' ')
    
    @classmethod
    def from_header(cls, header):
        return cls(bitcoin_data.hash256(bitcoin_data.block_header_type.pack(header)), header['previous_block'])
    
    def __init__(self, hash, previous_hash):
        self.hash, self.previous_hash = hash, previous_hash

class HeightTracker(object):
    '''Point this at a factory and let it take care of getting block heights'''
    
    def __init__(self, best_block_func, factory, backlog_needed):
        self._best_block_func = best_block_func
        self._factory = factory
        self._backlog_needed = backlog_needed
        
        self._tracker = forest.Tracker()
        
        self._watch1 = self._factory.new_headers.watch(self._heard_headers)
        self._watch2 = self._factory.new_block.watch(self._request)
        
        self._requested = set()
        self._clear_task = deferral.RobustLoopingCall(self._requested.clear)
        self._clear_task.start(60)
        
        self._last_notified_size = 0
        
        self.updated = variable.Event()
        
        self._think_task = deferral.RobustLoopingCall(self._think)
        self._think_task.start(15)
        self._think2_task = deferral.RobustLoopingCall(self._think2)
        self._think2_task.start(15)
    
    def _think(self):
        try:
            highest_head = max(self._tracker.heads, key=lambda h: self._tracker.get_height_and_last(h)[0]) if self._tracker.heads else None
            if highest_head is None:
                return # wait for think2
            height, last = self._tracker.get_height_and_last(highest_head)
            if height < self._backlog_needed:
                self._request(last)
        except:
            log.err(None, 'Error in HeightTracker._think:')
    
    def _think2(self):
        self._request(self._best_block_func())
    
    def _heard_headers(self, headers):
        changed = False
        for header in headers:
            hw = HeaderWrapper.from_header(header)
            if hw.hash in self._tracker.items:
                continue
            changed = True
            self._tracker.add(hw)
        if changed:
            self.updated.happened()
        self._think()
        
        if len(self._tracker.items) >= self._last_notified_size + 100:
            print 'Have %i/%i block headers' % (len(self._tracker.items), self._backlog_needed)
            self._last_notified_size = len(self._tracker.items)
    
    @defer.inlineCallbacks
    def _request(self, last):
        if last in self._tracker.items:
            return
        if last in self._requested:
            return
        self._requested.add(last)
        (yield self._factory.getProtocol()).send_getheaders(version=1, have=[], last=last)
    
    def get_height_rel_highest(self, block_hash):
        # callers: highest height can change during yields!
        best_height, best_last = self._tracker.get_height_and_last(self._best_block_func())
        height, last = self._tracker.get_height_and_last(block_hash)
        if last != best_last:
            return -1000000000 # XXX hack
        return height - best_height

@defer.inlineCallbacks
def get_height_rel_highest_func(bitcoind, factory, best_block_func, net):
    if '\ngetblock ' in (yield deferral.retry()(bitcoind.rpc_help)()):
        @deferral.DeferredCacher
        @defer.inlineCallbacks
        def height_cacher(block_hash):
            try:
                x = yield bitcoind.rpc_getblock('%x' % (block_hash,))
            except jsonrpc.Error_for_code(-5): # Block not found
                if not p2pool.DEBUG:
                    raise deferral.RetrySilentlyException()
                else:
                    raise
            defer.returnValue(x['blockcount'] if 'blockcount' in x else x['height'])
        best_height_cached = variable.Variable((yield deferral.retry()(height_cacher)(best_block_func())))
        def get_height_rel_highest(block_hash):
            this_height = height_cacher.call_now(block_hash, 0)
            best_height = height_cacher.call_now(best_block_func(), 0)
            best_height_cached.set(max(best_height_cached.value, this_height, best_height))
            return this_height - best_height_cached.value
    else:
        get_height_rel_highest = HeightTracker(best_block_func, factory, 5*net.SHARE_PERIOD*net.CHAIN_LENGTH/net.PARENT.BLOCK_PERIOD).get_height_rel_highest
    defer.returnValue(get_height_rel_highest)
