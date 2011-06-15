#!/usr/bin/python

from __future__ import division

import argparse
import subprocess
import os
import sys
import traceback
import random
import gdbm

from twisted.internet import reactor, defer
from twisted.web import server

import jsonrpc
import conv
import worker_interface
import util
import bitcoin_p2p
import p2p
import expiring_dict
import p2pool

class Chain(object):
    def __init__(self, chain_id_data):
        self.chain_id_data = chain_id_data
        
        self.share2s = {} # hash -> share2
        self.highest = util.Variable(None)
        
        self.shared = set() # set of hashes of shared shares
    
    def accept(self, share, net):
        if share.chain_id_data != self.chain_id_data:
            raise ValueError('share does not belong to this chain')
        
        if share.hash in self.share2s:
            return 'dup'
        
        if share.previous_share_hash is None:
            previous_height, previous_share2 = -1, None
        elif share.previous_share_hash not in self.share2s:
            return 'orphan'
        else:
            previous_height, previous_share2 = self.share2s[share.previous_share_hash]
        
        height = previous_height + 1
        
        share2 = share.check(self, height, previous_share2) # raises exceptions
        
        if share2.share is not share:
            raise ValueError()
        
        self.share2s[share.hash] = share2
        
        if self.highest.value is None or height > self.share2s[self.highest.value].height:
            self.highest.set(share.hash)
        
        return 'good'
    
    def get_highest_share2(self):
        return self.share2s[self.highest.value] if self.highest.value is not None else None

@defer.inlineCallbacks
def get_last_p2pool_block_hash(current_block_hash, get_block, net):
    block_hash = current_block_hash
    while True:
        if block_hash == net.ROOT_BLOCK:
            defer.returnValue(block_hash)
        block = yield get_block(block_hash)
        coinbase_data = block['txns'][0]['tx_ins'][0]['script']
        try:
            coinbase = p2pool.coinbase_type.unpack(coinbase_data, ignore_extra=True)
        except bitcoin_p2p.EarlyEnd:
            pass
        else:
            try:
                if coinbase['identifier'] == net.IDENTIFIER:
                    payouts = {}
                    for tx_out in block['txns'][0]['tx_outs']:
                        payouts[tx_out['script']] = payouts.get(tx_out['script'], 0) + tx_out['value']
                    subsidy = sum(payouts.itervalues())
                    if coinbase['subsidy'] == subsidy:
                        if payouts.get(net.SCRIPT, 0) >= subsidy//64:
                            defer.returnValue(block_hash)
            except Exception:
                print
                print 'Error matching block:'
                print 'block:', block
                traceback.print_exc()
                print
        block_hash = block['header']['previous_block']

@defer.inlineCallbacks
def getwork(bitcoind):
    while True:
        try:
            getwork_df, height_df = bitcoind.rpc_getwork(), bitcoind.rpc_getblocknumber()
            getwork, height = conv.BlockAttempt.from_getwork((yield getwork_df)), (yield height_df)
        except:
            print
            print 'Error getting work from bitcoind:'
            traceback.print_exc()
            print
            yield util.sleep(1)
            continue
        defer.returnValue((getwork, height))

@defer.inlineCallbacks
def main(args):
    try:
        net = p2pool.Testnet if args.testnet else p2pool.Main
        
        print name
        print
        
        # connect to bitcoind over JSON-RPC and do initial getwork
        url = 'http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port)
        print "Testing bitcoind RPC connection to '%s' with authorization '%s:%s'..." % (url, args.bitcoind_rpc_username, args.bitcoind_rpc_password)
        bitcoind = jsonrpc.Proxy(url, (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
        
        work, height = yield getwork(bitcoind)
        
        print '    ...success!'
        print '    Current block hash: %x height: %i' % (work.previous_block, height)
        print
        
        # connect to bitcoind over bitcoin-p2p and do checkorder to get pubkey to send payouts to
        print "Testing bitcoind P2P connection to '%s:%s'..." % (args.bitcoind_address, args.bitcoind_p2p_port)
        factory = bitcoin_p2p.ClientFactory(args.testnet)
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        
        while True:
            try:
                res = yield (yield factory.getProtocol()).check_order(order=bitcoin_p2p.Protocol.null_order)
                if res['reply'] != 'success':
                    print
                    print 'Error getting payout script:'
                    print res
                    print
                    continue
                my_script = res['script']
            except:
                print
                print 'Error getting payout script:'
                traceback.print_exc()
                print
            else:
                break
            yield util.sleep(1)
        
        print '    ...success!'
        print '    Payout script:', my_script.encode('hex')
        print
        
        @defer.inlineCallbacks
        def real_get_block(block_hash):
            block = yield (yield factory.getProtocol()).get_block(block_hash)
            print 'Got block %x' % (block_hash,)
            defer.returnValue(block)
        get_block = util.DeferredCacher(real_get_block, expiring_dict.ExpiringDict(3600))
        
        chains = expiring_dict.ExpiringDict(1000)
        def get_chain(chain_id_data):
            return chains.setdefault(chain_id_data, Chain(chain_id_data))
        # information affecting work that should trigger a long-polling update
        current_work = util.Variable(None)
        # information affecting work that should not trigger a long-polling update
        current_work2 = util.Variable(None)
        
        share_dbs = [gdbm.open(filename, 'cs') for filename in args.store_shares]
        
        @defer.inlineCallbacks
        def set_real_work():
            work, height = yield getwork(bitcoind)
            last_p2pool_block_hash = (yield get_last_p2pool_block_hash(work.previous_block, get_block, net))
            chain = get_chain(p2pool.chain_id_type.pack(dict(previous_p2pool_block=last_p2pool_block_hash, bits=work.bits)))
            current_work.set(dict(
                version=work.version,
                previous_block=work.previous_block,
                bits=work.bits,
                height=height + 1,
                current_chain=chain,
                highest_p2pool_share2=chain.get_highest_share2(),
                last_p2pool_block_hash=last_p2pool_block_hash,
            ))
            current_work2.set(dict(
                timestamp=work.timestamp,
            ))
        
        print 'Searching for last p2pool-generated block...'
        yield set_real_work()
        print '    ...success!'
        print '    Matched block %x' % (current_work.value['last_p2pool_block_hash'],)
        print
        
        # setup p2p logic and join p2pool network
        
        def share_share2(share2, ignore_peer=None):
            for peer in p2p_node.peers.itervalues():
                if peer is ignore_peer:
                    continue
                peer.send_share(share2.share)
            share2.chain.shared.add(share.hash)
        
        def p2pCallback(share, peer=None):
            if share.hash <= conv.bits_to_target(share.header['bits']):
                print 'Got block! Passing to bitcoind!', share.hash
                if factory.conn is not None:
                    factory.conn.addInv('block', share.as_block())
                else:
                    print "No bitcoind connection! Erp!"
            
            chain = get_chain(share.chain_id_data)
            res = chain.accept(share, net)
            if res == 'good':
                hash_data = bitcoin_p2p.HashType().pack(share.hash)
                for share_db in share_dbs:
                    share_db[hash_data] = share.block_data
                    share_db.sync()
                if chain is current_work.value['current_chain']:
                    print 'Accepted share, passing to peers. Hash: %x' % (share.hash,)
                    share_share(share, peer)
                else:
                    print 'Accepted share to non-current chain. Hash: %x' % (share.hash,)
            elif res == 'dup':
                print 'Got duplicate share, ignoring. Hash: %x' % (share.hash,)
            elif res == 'orphan':
                print 'Got share referencing unknown share, requesting past shares from peer. Hash: %x' % (share.hash,)
                peer.getsharesbychain(
                    chain_id=p2pool.chain_id_type.unpack(share.chain_id_data),
                    have=chain.highest.value[1].hash() if chain.highest.value[1] is not None else None
                )
            else:
                raise ValueError('unknown result from chain.accept - %r' % (res,))
            
            w = dict(current_work.value)
            w['highest_p2pool_share'] = w['current_chain'].get_highest_share()
            current_work.set(w)
            
            return bitcoin_p2p.block_hash(block['header']) <= net.TARGET_MULTIPLIER*conv.bits_to_target(block['header']['bits'])
        
        @defer.inlineCallbacks
        def getBlocksCallback2(chain_id_data, highest, contact):
            chain = get_chain(chain_id_data)
            
            def get_down(share_hash):
                blocks = []
                while share_hash in chain.shares:
                    share = chain.shares[share_hash][1]
                    blocks.append(share_hash)
                    
                    share_hash = share.previous_hash()
                    if share_hash is None:
                        break
                return blocks
            
            blocks = get_down(chain.highest.value[1].hash())
            have = set(get_down(highest) if highest is not None else [])
            
            for block in reversed(blocks):
                if block in have:
                    continue
                contact.block(chain.shares[block][1].block_data)
        
        def getBlocksCallback(chain_id, highest, contact):
            getBlocksCallback2(chain_id, highest, contact)
        
        print 'Joining p2pool network using TCP port %i...' % (args.p2pool_port,)
        
        def parse(x):
            if ':' in x:
                ip, port = x.split(':')
                return ip, int(port)
            else:
                return ip, {False: 9333, True: 19333}[args.testnet]
        
        if args.testnet:
            nodes = [('72.14.191.28', 19333)]
        else:
            nodes = [('72.14.191.28', 9333)]
        
        p2p_node = p2p.Node(
            port=args.p2pool_port,
            testnet=args.testnet,
            addr_store=gdbm.open(os.path.join(os.path.dirname(__file__), 'peers.dat'), 'cs'),
            mode=1 if args.low_bandwidth else 0,
            preferred_addrs=map(parse, args.p2pool_nodes) + nodes,
        )
        p2p_node.handle_share = p2pCallback
        p2p_node.handle_get_blocks = getBlocksCallback
        
        p2p_node.start()
        
        # send share when the chain changes to their chain
        def work_changed(new_work):
            #print 'Work changed:', new_work
            chain = new_work['current_chain']
            for share2 in chain.share2s.itervalues():
                if share2.share.hash not in chain.shared:
                    print "Sharing share of switched to chain. Hash:", share2.share.hash
                    share_share2(share2)
        current_work.changed.watch(work_changed)
        
        print '    ...success!'
        print
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on port %i...' % (args.worker_port,)
        
        # setup worker logic
        
        merkle_root_to_transactions = expiring_dict.ExpiringDict(1000)
        
        def compute(state):
            generate_txn, shares = p2pool.generate_transaction(
                last_p2pool_block_hash=state['last_p2pool_block_hash'],
                previous_share2=state['highest_p2pool_share2'],
                add_script=my_script,
                subsidy=50*100000000 >> state['height']//210000,
                nonce=random.randrange(2**64),
                net=net,
            )
            print 'Generating, have', shares.count(my_script) - 2, 'share(s) in the current chain.'
            transactions = [generate_txn] # XXX
            merkle_root = bitcoin_p2p.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = transactions # will stay for 1000 seconds
            ba = conv.BlockAttempt(state['version'], state['previous_block'], merkle_root, current_work2.value['timestamp'], state['bits'])
            return ba.getwork(net.TARGET_MULTIPLIER)
        
        def got_response(data):
            # match up with transactions
            header = conv.decode_data(data)
            transactions = merkle_root_to_transactions.get(header['merkle_root'], None)
            if transactions is None:
                print "Couldn't link returned work's merkle root with its transactions - should only happen if you recently restarted p2pool"
                return False
            share = p2pool.Share(header=header, txns=transactions)
            try:
                return p2pCallback(share)
            except:
                print
                print 'Error processing data received from worker:'
                traceback.print_exc()
                print
                return False
        
        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response)))
        
        print '    ...success!'
        print
        
        # done!
        
        print 'Started successfully!'
        print
        
        while True:
            yield set_real_work()
            yield util.sleep(1)
    except:
        print
        print 'Fatal error:'
        traceback.print_exc()
        print
    reactor.stop()

if __name__ == '__main__':
    try:
        __version__ = subprocess.Popen(['svnversion', os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
    except IOError:
        __version__ = 'unknown'
    
    name = 'p2pool (version %s)' % (__version__,)
    
    parser = argparse.ArgumentParser(description=name)
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('-t', '--testnet',
        help='use the testnet; make sure you change the ports too',
        action='store_true', default=False, dest='testnet')
    parser.add_argument('-s', '--store-shares', metavar='FILENAME',
        help='write shares to a database (not needed for normal usage)',
        type=str, action='append', default=[], dest='store_shares')
    
    p2pool_group = parser.add_argument_group('p2pool interface')
    p2pool_group.add_argument('-p', '--p2pool-port', metavar='PORT',
        help='use TCP port PORT to listen for connections (default: 9333 normally, 19333 for testnet) (forward this port from your router!)',
        type=int, action='store', default=None, dest='p2pool_port')
    p2pool_group.add_argument('-n', '--p2pool-node', metavar='ADDR[:PORT]',
        help='connect to existing p2pool node at ADDR listening on TCP port PORT (defaults to 9333 normally, 19333 for testnet), in addition to builtin addresses',
        type=str, action='append', default=[], dest='p2pool_nodes')
    parser.add_argument('-l', '--low-bandwidth',
        help='trade lower bandwidth usage for higher latency (reduced efficiency)',
        action='store_true', default=False, dest='low_bandwidth')
    
    worker_group = parser.add_argument_group('worker interface')
    worker_group.add_argument('-w', '--worker-port', metavar='PORT',
        help='listen on PORT for RPC connections from miners asking for work and providing responses (default: 9332)',
        type=int, action='store', default=9332, dest='worker_port')
    
    bitcoind_group = parser.add_argument_group('bitcoind interface')
    bitcoind_group.add_argument('--bitcoind-address', metavar='BITCOIND_ADDRESS',
        help='connect to a bitcoind at this address (default: 127.0.0.1)',
        type=str, action='store', default='127.0.0.1', dest='bitcoind_address')
    bitcoind_group.add_argument('--bitcoind-rpc-port', metavar='BITCOIND_RPC_PORT',
        help='connect to a bitcoind at this port over the RPC interface - used to get the current highest block via getwork (default: 8332)',
        type=int, action='store', default=8332, dest='bitcoind_rpc_port')
    bitcoind_group.add_argument('--bitcoind-p2p-port', metavar='BITCOIND_P2P_PORT',
        help='connect to a bitcoind at this port over the p2p interface - used to submit blocks and get the pubkey to generate to via an IP transaction (default: 8333 normally. 18333 for testnet)',
        type=int, action='store', default=None, dest='bitcoind_p2p_port')
    
    bitcoind_group.add_argument(metavar='BITCOIND_RPC_USERNAME',
        help='bitcoind RPC interface username',
        type=str, action='store', dest='bitcoind_rpc_username')
    bitcoind_group.add_argument(metavar='BITCOIND_RPC_PASSWORD',
        help='bitcoind RPC interface password',
        type=str, action='store', dest='bitcoind_rpc_password')
    
    args = parser.parse_args()
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = {False: 8333, True: 18333}[args.testnet]
    
    if args.p2pool_port is None:
        args.p2pool_port = {False: 9333, True: 19333}[args.testnet]
    
    reactor.callWhenRunning(main, args)
    reactor.run()
