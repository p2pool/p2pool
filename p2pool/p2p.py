from __future__ import division

import math
import random
import sys
import time

from twisted.internet import defer, protocol, reactor, task
from twisted.python import failure, log

import p2pool
from p2pool import data as p2pool_data
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, p2protocol, pack, variable

class PeerMisbehavingError(Exception):
    pass


def get_tx_packed_size(tx):
    """Get the packed size of a transaction, handling both normal and MWEB raw transactions."""
    if isinstance(tx, dict) and tx.get('_mweb'):
        # MWEB transaction stored as raw bytes
        return tx['_raw_size']
    return bitcoin_data.tx_type.packed_size(tx)


def fragment(f, **kwargs):
    try:
        f(**kwargs)
    except p2protocol.TooLong:
        fragment(f, **dict((k, v[:len(v)//2]) for k, v in kwargs.iteritems()))
        fragment(f, **dict((k, v[len(v)//2:]) for k, v in kwargs.iteritems()))

class Protocol(p2protocol.Protocol):
    VERSION = 3502  # Updated to match active Litecoin p2pool network (ml.toom.im)
    
    max_remembered_txs_size = 25000000
    
    def __init__(self, node, incoming):
        p2protocol.Protocol.__init__(self, node.net.PREFIX, 32000000, node.traffic_happened)
        self.node = node
        self.incoming = incoming
        
        self.other_version = None
        self.connected2 = False
    
    def connectionMade(self):
        self.factory.proto_made_connection(self)
        
        self.connection_lost_event = variable.Event()
        
        self.addr = self.transport.getPeer().host, self.transport.getPeer().port
        
        self.send_version(
            version=self.VERSION,
            services=0,
            addr_to=dict(
                services=0,
                address=self.transport.getPeer().host,
                port=self.transport.getPeer().port,
            ),
            addr_from=dict(
                services=0,
                address=self.transport.getHost().host,
                port=self.transport.getHost().port,
            ),
            nonce=self.node.nonce,
            sub_version=p2pool.__version__,
            mode=1,
            best_share_hash=self.node.best_share_hash_func(),
        )
        
        self.timeout_delayed = reactor.callLater(10, self._connect_timeout)
        
        self.get_shares = deferral.GenericDeferrer(
            max_id=2**256,
            func=lambda id, hashes, parents, stops: self.send_sharereq(id=id, hashes=hashes, parents=parents, stops=stops),
            timeout=15,
            on_timeout=self.disconnect,
        )
        
        self.remote_tx_hashes = set() # view of peer's known_txs # not actually initially empty, but sending txs instead of tx hashes won't hurt
        self.remote_remembered_txs_size = 0
        
        self.remembered_txs = {} # view of peer's mining_txs
        self.remembered_txs_size = 0
        self.known_txs_cache = {}
    
    def _connect_timeout(self):
        self.timeout_delayed = None
        print 'Handshake timed out, disconnecting from %s:%i' % self.addr
        self.disconnect()
    
    def packetReceived(self, command, payload2):
        try:
            if command != 'version' and not self.connected2:
                # This often happens during node restarts when peers have stale connections
                # Don't ban, just disconnect - they will reconnect with proper handshake
                print 'Peer %s:%i sent non-version first message, disconnecting (will not ban)' % self.addr
                self.disconnect()
                return
            p2protocol.Protocol.packetReceived(self, command, payload2)
        except PeerMisbehavingError, e:
            print 'Peer %s:%i misbehaving, will drop and ban. Reason:' % self.addr, e.message
            self.badPeerHappened()
    
    def badPeerHappened(self, bantime=3600):
        print "Bad peer banned:", self.addr
        self.disconnect()
        if self.transport.getPeer().host != '127.0.0.1': # never ban localhost
            host = self.transport.getPeer().host
            if not host in self.node.banscores:
                self.node.banscores[host] = 1
            else:
                self.node.banscores[host] += 1
            self.node.bans[self.transport.getPeer().host] = time.time() + bantime * self.node.banscores[host]**2
    
    def _timeout(self):
        self.timeout_delayed = None
        print 'Connection timed out, disconnecting from %s:%i' % self.addr
        self.disconnect()
    
    def sendAdvertisement(self):
        if self.node.serverfactory.listen_port is not None:
            host=self.node.external_ip
            port=self.node.serverfactory.listen_port.getHost().port
            if host is not None:
                if ':' in host:
                    host, port_str = host.split(':')
                    port = int(port_str)
                if p2pool.DEBUG:
                    print 'Advertising for incoming connections: %s:%i' % (host, port)
                # Advertise given external IP address, just as if there were another peer behind us, with that address, who asked us to advertise it for them
                self.send_addrs(addrs=[
                    dict(
                        address=dict(
                            services=self.other_services,
                            address=host,
                            port=port,
                        ),
                        timestamp=int(time.time()),
                    ),
                ])
            else:
                if p2pool.DEBUG:
                    print 'Advertising for incoming connections'
                # Ask peer to advertise what it believes our IP address to be
                self.send_addrme(port=port)

    message_version = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('services', pack.IntType(64)),
        ('addr_to', bitcoin_data.address_type),
        ('addr_from', bitcoin_data.address_type),
        ('nonce', pack.IntType(64)),
        ('sub_version', pack.VarStrType()),
        ('mode', pack.IntType(32)), # always 1 for legacy compatibility
        ('best_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
    ])
    def handle_version(self, version, services, addr_to, addr_from, nonce, sub_version, mode, best_share_hash):
        print "Peer %s:%s says protocol version is %s, client version %s" % (addr_from['address'], addr_from['port'], version, sub_version)
        if self.other_version is not None:
            # This can happen during simultaneous connection attempts - just disconnect, don't ban
            print 'Peer %s:%i sent duplicate version message, disconnecting (will not ban)' % self.addr
            self.disconnect()
            return
        if version < getattr(self.node.net, 'MINIMUM_PROTOCOL_VERSION', 1400):
            raise PeerMisbehavingError('peer too old')
        
        self.other_version = version
        self.other_sub_version = sub_version[:512]
        self.other_services = services
        
        if nonce == self.node.nonce:
            raise PeerMisbehavingError('was connected to self')
        if nonce in self.node.peers:
            if p2pool.DEBUG:
                print 'Detected duplicate connection, disconnecting from %s:%i' % self.addr
            self.disconnect()
            return
        
        self.nonce = nonce
        self.connected2 = True
        
        self.timeout_delayed.cancel()
        self.timeout_delayed = reactor.callLater(100, self._timeout)
        
        old_dataReceived = self.dataReceived
        def new_dataReceived(data):
            if self.timeout_delayed is not None:
                self.timeout_delayed.reset(100)
            old_dataReceived(data)
        self.dataReceived = new_dataReceived
        
        self.factory.proto_connected(self)
        
        self._stop_thread = deferral.run_repeatedly(lambda: [
            self.send_ping(),
        random.expovariate(1/100)][-1])
        
        if self.node.advertise_ip:
            self._stop_thread2 = deferral.run_repeatedly(lambda: [
                self.sendAdvertisement(),
            random.expovariate(1/(100*len(self.node.peers) + 1))][-1])
        
        if best_share_hash is not None:
            self.node.handle_share_hashes([best_share_hash], self)
        
        if self.node.node.cur_share_ver >= 34:
            return

        def add_to_remote_view_of_my_known_txs(added):
            if added:
                self.send_have_tx(tx_hashes=list(added.keys()))
        
        watch_id0 = self.node.known_txs_var.added.watch(add_to_remote_view_of_my_known_txs)
        self.connection_lost_event.watch(lambda: self.node.known_txs_var.added.unwatch(watch_id0))
        
        def remove_from_remote_view_of_my_known_txs(removed):
            if removed:
                self.send_losing_tx(tx_hashes=list(removed.keys()))
                
                # cache forgotten txs here for a little while so latency of "losing_tx" packets doesn't cause problems
                key = max(self.known_txs_cache) + 1 if self.known_txs_cache else 0
                self.known_txs_cache[key] = removed #dict((h, before[h]) for h in removed)
                reactor.callLater(20, self.known_txs_cache.pop, key)
        watch_id1 = self.node.known_txs_var.removed.watch(remove_from_remote_view_of_my_known_txs)
        self.connection_lost_event.watch(lambda: self.node.known_txs_var.removed.unwatch(watch_id1))
        
        def update_remote_view_of_my_known_txs(before, after):
            t0 = time.time()
            added = set(after) - set(before)
            removed = set(before) - set(after)
            if added:
                self.send_have_tx(tx_hashes=list(added))
            if removed:
                self.send_losing_tx(tx_hashes=list(removed))
                
                # cache forgotten txs here for a little while so latency of "losing_tx" packets doesn't cause problems
                key = max(self.known_txs_cache) + 1 if self.known_txs_cache else 0
                self.known_txs_cache[key] = dict((h, before[h]) for h in removed)
                reactor.callLater(20, self.known_txs_cache.pop, key)
            t1 = time.time()
            if p2pool.BENCH and (t1-t0) > .01: print "%8.3f ms for update_remote_view_of_my_known_txs" % ((t1-t0)*1000.)
        watch_id2 = self.node.known_txs_var.transitioned.watch(update_remote_view_of_my_known_txs)
        self.connection_lost_event.watch(lambda: self.node.known_txs_var.transitioned.unwatch(watch_id2))
        
        self.send_have_tx(tx_hashes=self.node.known_txs_var.value.keys())
        
        def update_remote_view_of_my_mining_txs(before, after):
            t0 = time.time()
            added = set(after) - set(before)
            removed = set(before) - set(after)
            if removed:
                self.send_forget_tx(tx_hashes=list(removed))
                self.remote_remembered_txs_size -= sum(100 + get_tx_packed_size(before[x]) for x in removed)
            if added:
                self.remote_remembered_txs_size += sum(100 + get_tx_packed_size(after[x]) for x in added)
                assert self.remote_remembered_txs_size <= self.max_remembered_txs_size
                fragment(self.send_remember_tx, tx_hashes=[x for x in added if x in self.remote_tx_hashes], txs=[after[x] for x in added if x not in self.remote_tx_hashes])
            t1 = time.time()
            if p2pool.BENCH and (t1-t0) > .01: print "%8.3f ms for update_remote_view_of_my_mining_txs" % ((t1-t0)*1000.)

        watch_id2 = self.node.mining_txs_var.transitioned.watch(update_remote_view_of_my_mining_txs)
        self.connection_lost_event.watch(lambda: self.node.mining_txs_var.transitioned.unwatch(watch_id2))
        
        self.remote_remembered_txs_size += sum(100 + get_tx_packed_size(x) for x in self.node.mining_txs_var.value.values())
        assert self.remote_remembered_txs_size <= self.max_remembered_txs_size
        fragment(self.send_remember_tx, tx_hashes=[], txs=self.node.mining_txs_var.value.values())
    
    message_ping = pack.ComposedType([])
    def handle_ping(self):
        pass
    
    message_addrme = pack.ComposedType([
        ('port', pack.IntType(16)),
    ])
    def handle_addrme(self, port):
        host = self.transport.getPeer().host
        #print 'addrme from', host, port
        if host == '127.0.0.1':
            if random.random() < .8 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrme(port=port) # services...
        else:
            self.node.got_addr((self.transport.getPeer().host, port), self.other_services, int(time.time()))
            if random.random() < .8 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrs(addrs=[
                    dict(
                        address=dict(
                            services=self.other_services,
                            address=host,
                            port=port,
                        ),
                        timestamp=int(time.time()),
                    ),
                ])
    
    message_addrs = pack.ComposedType([
        ('addrs', pack.ListType(pack.ComposedType([
            ('timestamp', pack.IntType(64)),
            ('address', bitcoin_data.address_type),
        ]))),
    ])
    def handle_addrs(self, addrs):
        for addr_record in addrs:
            self.node.got_addr((addr_record['address']['address'], addr_record['address']['port']), addr_record['address']['services'], min(int(time.time()), addr_record['timestamp']))
            if random.random() < .8 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrs(addrs=[addr_record])
    
    message_getaddrs = pack.ComposedType([
        ('count', pack.IntType(32)),
    ])
    def handle_getaddrs(self, count):
        if count > 100:
            count = 100
        self.send_addrs(addrs=[
            dict(
                timestamp=int(self.node.addr_store[host, port][2]),
                address=dict(
                    services=self.node.addr_store[host, port][0],
                    address=host,
                    port=port,
                ),
            ) for host, port in
            self.node.get_good_peers(count)
        ])
    
    message_shares = pack.ComposedType([
        ('shares', pack.ListType(p2pool_data.share_type)),
    ])
    def handle_shares(self, shares):
        t0 = time.time()
        result = []
        for wrappedshare in shares:
            if wrappedshare['type'] < p2pool_data.Share.VERSION: continue
            share = p2pool_data.load_share(wrappedshare, self.node.net, self.addr)
            if 13 <= wrappedshare['type'] < 34:
                txs = []
                share_has_unknown_txs = False
                for tx_hash in share.share_info['new_transaction_hashes']:
                    if tx_hash in self.node.known_txs_var.value:
                        tx = self.node.known_txs_var.value[tx_hash]
                    else:
                        for cache in self.known_txs_cache.itervalues():
                            if tx_hash in cache:
                                tx = cache[tx_hash]
                                if p2pool.DEBUG:
                                    print 'Transaction %064x rescued from peer latency cache!' % (tx_hash,)
                                break
                        else:
                            # Transaction not found - this can happen with mempool timing differences
                            # or MWEB transactions. Don't disconnect, just skip this share.
                            if p2pool.DEBUG:
                                print >>sys.stderr, '[P2P] Share references unknown transaction %064x - skipping share' % (tx_hash,)
                            share_has_unknown_txs = True
                            break
                    txs.append(tx)
                if share_has_unknown_txs:
                    # Skip this share - we can't validate it without all transactions
                    continue
            else:
                txs = None
            
            result.append((share, txs))
            
        self.node.handle_shares(result, self)
        t1 = time.time()
        if p2pool.BENCH: print "%8.3f ms for %i shares in handle_shares (%3.3f ms/share)" % ((t1-t0)*1000., len(shares), (t1-t0)*1000./ max(1, len(shares)))

    
    def sendShares(self, shares, tracker, known_txs, include_txs_with=[]):
        t0 = time.time()
        tx_hashes = set()
        hashes_to_send = []
        for share in shares:
            if share.VERSION >= 34:
                continue
            elif share.VERSION >= 13:
                # send full transaction for every new_transaction_hash that peer does not know
                for tx_hash in share.share_info['new_transaction_hashes']:
                    if tx_hash not in known_txs:
                        # Transaction not in our known_txs - this can happen when:
                        # 1. Share arrives before we've seen the transaction in GBT
                        # 2. MWEB transaction that we couldn't parse (should be fixed now)
                        # 3. Transaction was evicted from mempool
                        # Don't assert, just skip sending this tx - peer likely has it already
                        if p2pool.DEBUG:
                            print "[P2P] WARN: Share references unknown tx %064x - skipping relay of this tx" % tx_hash
                        continue
                    if tx_hash not in self.remote_tx_hashes:
                        tx_hashes.add(tx_hash)
                continue
            if share.hash in include_txs_with:
                x = share.get_other_tx_hashes(tracker)
                if x is not None:
                    tx_hashes.update(x)
        
            hashes_to_send = [x for x in tx_hashes if x not in self.node.mining_txs_var.value and x in known_txs]
            all_hashes = share.share_info['new_transaction_hashes']
            new_tx_size = sum(100 + get_tx_packed_size(known_txs[x]) for x in hashes_to_send)
            all_tx_size = sum(100 + get_tx_packed_size(known_txs[x]) for x in all_hashes)
            print "Sending a share with %i txs (%i new) totaling %i msg bytes (%i new)" % (len(all_hashes), len(hashes_to_send), all_tx_size, new_tx_size)

        if tx_hashes:
            hashes_to_send = [x for x in tx_hashes if x not in self.node.mining_txs_var.value and x in known_txs]
            new_tx_size = sum(100 + get_tx_packed_size(known_txs[x]) for x in hashes_to_send)

            new_remote_remembered_txs_size = self.remote_remembered_txs_size + new_tx_size
            if new_remote_remembered_txs_size > self.max_remembered_txs_size:
                raise ValueError('shares have too many txs')
            self.remote_remembered_txs_size = new_remote_remembered_txs_size

            fragment(self.send_remember_tx, tx_hashes=[x for x in hashes_to_send if x in self.remote_tx_hashes], txs=[known_txs[x] for x in hashes_to_send if x not in self.remote_tx_hashes])

        fragment(self.send_shares, shares=[share.as_share() for share in shares])

        if hashes_to_send:
            self.send_forget_tx(tx_hashes=hashes_to_send)

            self.remote_remembered_txs_size -= new_tx_size
        t1 = time.time()
        if p2pool.BENCH: print "%8.3f ms for %i shares in sendShares (%3.3f ms/share)" % ((t1-t0)*1000., len(shares), (t1-t0)*1000./ max(1, len(shares)))

    
    
    message_sharereq = pack.ComposedType([
        ('id', pack.IntType(256)),
        ('hashes', pack.ListType(pack.IntType(256))),
        ('parents', pack.VarIntType()),
        ('stops', pack.ListType(pack.IntType(256))),
    ])
    def handle_sharereq(self, id, hashes, parents, stops):
        shares = self.node.handle_get_shares(hashes, parents, stops, self)
        try:
            self.send_sharereply(id=id, result='good', shares=[share.as_share() for share in shares])
        except p2protocol.TooLong:
            self.send_sharereply(id=id, result='too long', shares=[])
    
    message_sharereply = pack.ComposedType([
        ('id', pack.IntType(256)),
        ('result', pack.EnumType(pack.VarIntType(), {0: 'good', 1: 'too long', 2: 'unk2', 3: 'unk3', 4: 'unk4', 5: 'unk5', 6: 'unk6'})),
        ('shares', pack.ListType(p2pool_data.share_type)),
    ])
    class ShareReplyError(Exception): pass
    def handle_sharereply(self, id, result, shares):
        if result == 'good':
            res = [p2pool_data.load_share(share, self.node.net, self.addr) for share in shares if share['type'] >= p2pool_data.Share.VERSION]
        else:
            res = failure.Failure(self.ShareReplyError(result))
        self.get_shares.got_response(id, res)
    
    
    message_bestblock = pack.ComposedType([
        ('header', bitcoin_data.block_header_type),
    ])
    def handle_bestblock(self, header):
        self.node.handle_bestblock(header, self)
    
    
    message_have_tx = pack.ComposedType([
        ('tx_hashes', pack.ListType(pack.IntType(256))),
    ])
    def handle_have_tx(self, tx_hashes):
        #assert self.remote_tx_hashes.isdisjoint(tx_hashes)
        self.remote_tx_hashes.update(tx_hashes)
        while len(self.remote_tx_hashes) > 10000:
            self.remote_tx_hashes.pop()
    message_losing_tx = pack.ComposedType([
        ('tx_hashes', pack.ListType(pack.IntType(256))),
    ])
    def handle_losing_tx(self, tx_hashes):
        t0 = time.time()
        #assert self.remote_tx_hashes.issuperset(tx_hashes)
        self.remote_tx_hashes.difference_update(tx_hashes)
        t1 = time.time()
        if p2pool.BENCH and (t1-t0) > .01: print "%8.3f ms for %i txs in handle_losing_tx (%3.3f ms/tx)" % ((t1-t0)*1000., len(tx_hashes), (t1-t0)*1000./ max(1, len(tx_hashes)))

    
    
    message_remember_tx = pack.ComposedType([
        ('tx_hashes', pack.ListType(pack.IntType(256))),
        ('txs', pack.ListType(bitcoin_data.tx_type)),
    ])
    def handle_remember_tx(self, tx_hashes, txs):
        t0 = time.time()
        for tx_hash in tx_hashes:
            if tx_hash in self.remembered_txs:
                print >>sys.stderr, 'Peer referenced transaction twice, disconnecting'
                self.disconnect()
                return
            
            if tx_hash in self.node.known_txs_var.value:
                tx = self.node.known_txs_var.value[tx_hash]
            else:
                for cache in self.known_txs_cache.itervalues():
                    if tx_hash in cache:
                        tx = cache[tx_hash]
                        print 'Transaction %064x rescued from peer latency cache!' % (tx_hash,)
                        break
                else:
                    # Transaction not found - this can happen with mempool timing differences
                    # or MWEB transactions. Don't disconnect, just skip this transaction.
                    if p2pool.DEBUG:
                        print >>sys.stderr, '[P2P] remember_tx: Unknown transaction %064x - skipping' % (tx_hash,)
                    continue
            
            self.remembered_txs[tx_hash] = tx
            self.remembered_txs_size += 100 + get_tx_packed_size(tx)
        added_known_txs = {}
        warned = False
        for tx in txs:
            tx_hash = bitcoin_data.hash256(bitcoin_data.tx_type.pack(tx))
            if tx_hash in self.remembered_txs:
                print >>sys.stderr, 'Peer referenced transaction twice, disconnecting'
                self.disconnect()
                return
            
            if tx_hash in self.node.known_txs_var.value and not warned and p2pool.DEBUG:
                print 'Peer sent entire transaction %064x that was already received' % (tx_hash,)
                warned = True
            
            self.remembered_txs[tx_hash] = tx
            self.remembered_txs_size += 100 + get_tx_packed_size(tx)
            added_known_txs[tx_hash] = tx
        self.node.known_txs_var.add(added_known_txs)
        if self.remembered_txs_size >= self.max_remembered_txs_size:
            raise PeerMisbehavingError('too much transaction data stored')
        t1 = time.time()
        if p2pool.BENCH and (t1-t0) > .01: print "%8.3f ms for %i txs in p2p.py:handle_remember_tx (%3.3f ms/tx)" % ((t1-t0)*1000., len(tx_hashes), ((t1-t0)*1000. / max(1,len(tx_hashes)) ))
    message_forget_tx = pack.ComposedType([
        ('tx_hashes', pack.ListType(pack.IntType(256))),
    ])
    def handle_forget_tx(self, tx_hashes):
        for tx_hash in tx_hashes:
            self.remembered_txs_size -= 100 + get_tx_packed_size(self.remembered_txs[tx_hash])
            assert self.remembered_txs_size >= 0
            del self.remembered_txs[tx_hash]
    
    
    def connectionLost(self, reason):
        self.connection_lost_event.happened()
        if self.timeout_delayed is not None:
            self.timeout_delayed.cancel()
        if self.connected2:
            self.factory.proto_disconnected(self, reason)
            self._stop_thread()
            if self.node.advertise_ip:
                self._stop_thread2()
            self.connected2 = False
        self.factory.proto_lost_connection(self, reason)
        if p2pool.DEBUG:
            print "Peer connection lost:", self.addr, reason
        self.get_shares.respond_all(reason)
    
    @defer.inlineCallbacks
    def do_ping(self):
        start = reactor.seconds()
        yield self.get_shares(hashes=[0], parents=0, stops=[])
        end = reactor.seconds()
        defer.returnValue(end - start)

class ServerFactory(protocol.ServerFactory):
    def __init__(self, node, max_conns):
        self.node = node
        self.max_conns = max_conns
        
        self.conns = {}
        self.running = False
        self.listen_port = None
    
    def buildProtocol(self, addr):
        if sum(self.conns.itervalues()) >= self.max_conns or self.conns.get(self._host_to_ident(addr.host), 0) >= 3:
            return None
        if addr.host in self.node.bans and self.node.bans[addr.host] > time.time():
            return None
        p = Protocol(self.node, True)
        p.factory = self
        if p2pool.DEBUG:
            print "Got peer connection from:", addr
        return p
    
    def _host_to_ident(self, host):
        a, b, c, d = host.split('.')
        return a, b
    
    def proto_made_connection(self, proto):
        ident = self._host_to_ident(proto.transport.getPeer().host)
        self.conns[ident] = self.conns.get(ident, 0) + 1
    def proto_lost_connection(self, proto, reason):
        ident = self._host_to_ident(proto.transport.getPeer().host)
        self.conns[ident] -= 1
        if not self.conns[ident]:
            del self.conns[ident]
    
    def proto_connected(self, proto):
        self.node.got_conn(proto)
    def proto_disconnected(self, proto, reason):
        self.node.lost_conn(proto, reason)
    
    def start(self):
        assert not self.running
        self.running = True
        
        def attempt_listen():
            if self.running:
                self.listen_port = reactor.listenTCP(self.node.port, self)
        deferral.retry('Error binding to P2P port:', traceback=False)(attempt_listen)()
    
    def stop(self):
        assert self.running
        self.running = False
        
        return self.listen_port.stopListening()

class ClientFactory(protocol.ClientFactory):
    def __init__(self, node, desired_conns, max_attempts):
        self.node = node
        self.desired_conns = desired_conns
        self.max_attempts = max_attempts
        
        self.attempts = set()
        self.conns = set()
        self.running = False
    
    def _host_to_ident(self, host):
        a, b, c, d = host.split('.')
        return a, b
    
    def buildProtocol(self, addr):
        p = Protocol(self.node, False)
        p.factory = self
        return p
    
    def startedConnecting(self, connector):
        ident = self._host_to_ident(connector.getDestination().host)
        if ident in self.attempts:
            raise AssertionError('already have attempt')
        self.attempts.add(ident)
    
    def clientConnectionFailed(self, connector, reason):
        self.attempts.remove(self._host_to_ident(connector.getDestination().host))
    
    def clientConnectionLost(self, connector, reason):
        self.attempts.remove(self._host_to_ident(connector.getDestination().host))
    
    def proto_made_connection(self, proto):
        pass
    def proto_lost_connection(self, proto, reason):
        pass
    
    def proto_connected(self, proto):
        self.conns.add(proto)
        self.node.got_conn(proto)
    def proto_disconnected(self, proto, reason):
        self.conns.remove(proto)
        self.node.lost_conn(proto, reason)
    
    def start(self):
        assert not self.running
        self.running = True
        self._stop_thinking = deferral.run_repeatedly(self._think)
    def stop(self):
        assert self.running
        self.running = False
        self._stop_thinking()
    
    def _think(self):
        try:
            if len(self.conns) < self.desired_conns and len(self.attempts) < self.max_attempts and self.node.addr_store:
                (host, port), = self.node.get_good_peers(1)
                
                if self._host_to_ident(host) in self.attempts:
                    pass
                elif host in self.node.bans and self.node.bans[host] > time.time():
                    pass
                else:
                    #print 'Trying to connect to', host, port
                    reactor.connectTCP(host, port, self, timeout=5)
        except:
            log.err()
        
        return random.expovariate(1/1)

class SingleClientFactory(protocol.ReconnectingClientFactory):
    def __init__(self, node):
        self.node = node
    
    def buildProtocol(self, addr):
        p = Protocol(self.node, incoming=False)
        p.factory = self
        return p
    
    def proto_made_connection(self, proto):
        pass
    def proto_lost_connection(self, proto, reason):
        pass
    
    def proto_connected(self, proto):
        self.resetDelay()
        self.node.got_conn(proto)
    def proto_disconnected(self, proto, reason):
        self.node.lost_conn(proto, reason)

class Node(object):
    def __init__(self, best_share_hash_func, port, net, addr_store={}, connect_addrs=set(), desired_outgoing_conns=10, max_outgoing_attempts=30, max_incoming_conns=50, preferred_storage=1000, known_txs_var=variable.VariableDict({}), mining_txs_var=variable.VariableDict({}), mining2_txs_var=variable.VariableDict({}), advertise_ip=True, external_ip=None):
        self.best_share_hash_func = best_share_hash_func
        self.port = port
        self.net = net
        self.addr_store = dict(addr_store)
        self.connect_addrs = connect_addrs
        self.preferred_storage = preferred_storage
        self.known_txs_var = known_txs_var
        self.mining_txs_var = mining_txs_var
        self.mining2_txs_var = mining2_txs_var
        self.advertise_ip = advertise_ip
        self.external_ip = external_ip
        
        self.traffic_happened = variable.Event()
        self.nonce = random.randrange(2**64)
        self.peers = {}
        self.bans = {} # address -> end_time
        self.banscores = {} # address -> how naughty this peer has been recently
        self.clientfactory = ClientFactory(self, desired_outgoing_conns, max_outgoing_attempts)
        self.serverfactory = ServerFactory(self, max_incoming_conns)
        self.running = False
    
    def start(self):
        if self.running:
            raise ValueError('already running')
        
        self.clientfactory.start()
        self.serverfactory.start()
        self.singleclientconnectors = [reactor.connectTCP(addr, port, SingleClientFactory(self)) for addr, port in self.connect_addrs]
        
        self.running = True
        
        self._stop_thinking = deferral.run_repeatedly(self._think)
        self.forgiveness_task = task.LoopingCall(self.forgive_transgressions)
        self.forgiveness_task.start(3600.)

    def forgive_transgressions(self):
        for host in list(self.banscores.keys()):
            self.banscores[host] -= 1
            if self.banscores[host] <= 0:
                del self.banscores[host]
    
    def _think(self):
        try:
            if len(self.addr_store) < self.preferred_storage and self.peers:
                random.choice(self.peers.values()).send_getaddrs(count=8)
        except:
            log.err()
        
        return random.expovariate(1/20)
    
    @defer.inlineCallbacks
    def stop(self):
        if not self.running:
            raise ValueError('already stopped')
        
        self.running = False
        
        self._stop_thinking()
        yield self.clientfactory.stop()
        yield self.serverfactory.stop()
        for singleclientconnector in self.singleclientconnectors:
            yield singleclientconnector.factory.stopTrying()
            yield singleclientconnector.disconnect()
        del self.singleclientconnectors
    
    def got_conn(self, conn):
        if conn.nonce in self.peers:
            raise ValueError('already have peer')
        self.peers[conn.nonce] = conn
        
        print '%s peer %s:%i established. p2pool version: %i %r' % ('Incoming connection from' if conn.incoming else 'Outgoing connection to', conn.addr[0], conn.addr[1], conn.other_version, conn.other_sub_version)
        
    def lost_conn(self, conn, reason):
        if conn.nonce not in self.peers:
            raise ValueError('''don't have peer''')
        if conn is not self.peers[conn.nonce]:
            raise ValueError('wrong conn')
        del self.peers[conn.nonce]
        
        print 'Lost peer %s:%i - %s' % (conn.addr[0], conn.addr[1], reason.getErrorMessage())
    
    
    def got_addr(self, (host, port), services, timestamp):
        if (host, port) in self.addr_store:
            old_services, old_first_seen, old_last_seen = self.addr_store[host, port]
            self.addr_store[host, port] = services, old_first_seen, max(old_last_seen, timestamp)
        else:
            if len(self.addr_store) < 10000:
                self.addr_store[host, port] = services, timestamp, timestamp
    
    def handle_shares(self, shares, peer):
        print 'handle_shares', (shares, peer)
    
    def handle_share_hashes(self, hashes, peer):
        print 'handle_share_hashes', (hashes, peer)
    
    def handle_get_shares(self, hashes, parents, stops, peer):
        print 'handle_get_shares', (hashes, parents, stops, peer)
    
    def handle_bestblock(self, header, peer):
        print 'handle_bestblock', header
    
    def get_good_peers(self, max_count):
        t = time.time()
        return [x[0] for x in sorted(self.addr_store.iteritems(), key=lambda (k, (services, first_seen, last_seen)):
            -math.log(max(3600, last_seen - first_seen))/math.log(max(3600, t - last_seen))*random.expovariate(1)
        )][:max_count]
