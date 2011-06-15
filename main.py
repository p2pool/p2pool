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

# TARGET_MULTIPLIER needs to be less than the current difficulty to prevent miner clients from missing shares

class Testnet(object):
    TARGET_MULTIPLIER = SPREAD = 30
    ROOT_BLOCK = 0x3575d1e7b40fe37ad12d41169a1012d26df5f3c35486e2abfbe9d2c
    SCRIPT = '410489175c7658845fd7c33d61029ebf4042e8386443ff6e6628fdb5ac938c31072dc61cee691ae1e8355c3a87cb4813cc9bf036fdb09078d35eacf9e9ab52374ebeac'.decode('hex')
    IDENTIFIER = 0x808330dc87e313b7

class Main(object):
    TARGET_MULTIPLIER = SPREAD = 256
    ROOT_BLOCK = 0xe891d9dfc38eca8f13e2e6d81e3e68c018c2500230961462cb0
    SCRIPT = '410441ccbae5ca6ecfaa014028b0c49df2cd5588cb6058ac260d650bc13c9ec466f95c7a6d80a3ea7f7b8e2e87e49b96081e9b20415b06433d7a5b6a156b58690d96ac'.decode('hex')
    IDENTIFIER = 0x49ddc0b4938708ad

coinbase_type = bitcoin_p2p.ComposedType([
    ('identifier', bitcoin_p2p.StructType('<Q')),
    ('last_p2pool_block_hash', bitcoin_p2p.HashType()),
    ('previous_p2pool_share_hash', bitcoin_p2p.HashType()),
    ('subsidy', bitcoin_p2p.StructType('<Q')),
    ('last_share_index', bitcoin_p2p.StructType('<I')),
    ('nonce', bitcoin_p2p.StructType('<Q')),
])

class Node(object):
    def __init__(self, block):
        self.block = block
        self.block_data = bitcoin_p2p.block.pack(block)
        self.block_hash = bitcoin_p2p.block_hash(block['header'])
        self.coinbase = coinbase_type.unpack(self.block['txns'][0]['tx_ins'][0]['script'], ignore_extra=True)
        self.shared = False
    
    def hash(self):
        return self.block_hash
    
    def previous_hash(self):
        hash_ = self.coinbase['previous_p2pool_share_hash']
        if hash_ == 2**256 - 1:
            return None
        return hash_
    
    def chain_id(self):
        return (self.coinbase['last_p2pool_block_hash'], self.block['header']['bits'])
    
    def check(self, chain, height2, previous_node):
        # check bits and target
        if self.chain_id() != (chain.last_p2pool_block_hash, chain.bits):
            raise ValueError('wrong chain')
        if self.block_hash > net.TARGET_MULTIPLIER*conv.bits_to_target(chain.bits):
            raise ValueError('not enough work!')
        
        t = self.block['txns'][0]
        t2, shares = generate_transaction(
            last_p2pool_block_hash=chain.last_p2pool_block_hash,
            previous_node=previous_node,
            add_script=t['tx_outs'][self.coinbase['last_share_index']]['script'],
            subsidy=self.coinbase['subsidy'],
            nonce=self.coinbase['nonce'],
        )
        if t2 != t:
            raise ValueError('invalid generate txn')
        #print 'ACCEPTED SHARE'
        #print self.block
        #print
        #print self.coinbase
        #print
        #print
        self.shares = shares
        self.height2 = height2
        return True
    
    def flag_shared(self):
        self.shared = True

class Chain(object):
    def __init__(self, (last_p2pool_block_hash, bits)):
        self.last_p2pool_block_hash = last_p2pool_block_hash
        self.bits = bits
        
        self.nodes = {} # hash -> (height, node)
        self.highest = util.Variable((-1, None)) # (height, node) could be hash
    
    def accept(self, node):
        if node.chain_id() != (self.last_p2pool_block_hash, self.bits):
            raise ValueError('block does not belong to this chain')
        
        hash_ = node.hash()
        
        if hash_ in self.nodes:
            return 'dup'
        
        previous_hash = node.previous_hash()
        
        if previous_hash is None:
            previous_height, previous_node = -1, None
        elif previous_hash not in self.nodes:
            return 'orphan'
        else:
            previous_height, previous_node = self.nodes[previous_hash]
        
        height = previous_height + 1
        
        if not node.check(self, height, previous_node):
            raise ValueError('node check failed')
        
        self.nodes[hash_] = (height, node)
        
        if height > self.highest.value[0]:
            self.highest.set((height, node))
        
        return 'good'

def generate_transaction(last_p2pool_block_hash, previous_node, add_script, subsidy, nonce):
    shares = (previous_node.shares if previous_node is not None else [net.SCRIPT]*net.SPREAD)[1:-1] + [add_script, add_script]
    
    dest_weights = {}
    for script in shares:
        dest_weights[script] = dest_weights.get(script, 0) + 1
    total_weight = sum(dest_weights.itervalues())
    
    amounts = dict((script, subsidy*weight*63//(64*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy//64 # prevent fake previous p2pool blocks
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    #print 'generate_transaction. height:', 0 if previous_node is None else previous_node.height2 + 1, 'amounts:', [x/100000000 for x in amounts.itervalues()]
    
    dests = sorted(amounts.iterkeys())
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=dict(index=4294967295, hash=0),
            sequence=4294967295,
            script=coinbase_type.pack(dict(
                identifier=net.IDENTIFIER,
                last_p2pool_block_hash=last_p2pool_block_hash,
                previous_p2pool_share_hash=previous_node.hash() if previous_node is not None else 2**256 - 1,
                subsidy=subsidy,
                last_share_index=dests.index(add_script),
                nonce=nonce,
            )),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    ), shares

@defer.inlineCallbacks
def get_last_p2pool_block_hash(current_block_hash, get_block):
    block_hash = current_block_hash
    while True:
        if block_hash == net.ROOT_BLOCK:
            defer.returnValue(block_hash)
        block = yield get_block(block_hash)
        coinbase_data = block['txns'][0]['tx_ins'][0]['script']
        try:
            coinbase = coinbase_type.unpack(coinbase_data, ignore_extra=True)
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
def main():
    try:
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
        
        chains = expiring_dict.ExpiringDict(100) # XXX
        # information affecting work that should trigger a long-polling update
        current_work = util.Variable(None)
        # information affecting work that should not trigger a long-polling update
        current_work2 = util.Variable(None)
        
        share_dbs = [gdbm.open(filename, 'cs') for filename in args.store_shares]
        
        @defer.inlineCallbacks
        def get_real_work():
            work, height = yield getwork(bitcoind)
            last_p2pool_block_hash = (yield get_last_p2pool_block_hash(work.previous_block, get_block))
            chain = chains.setdefault((last_p2pool_block_hash, work.bits), Chain((last_p2pool_block_hash, work.bits)))
            current_work.set(dict(
                version=work.version,
                previous_block=work.previous_block,
                bits=work.bits,
                height=height + 1,
                current_chain=chain,
                highest_p2pool_share=chain.highest.value[1],
                last_p2pool_block_hash=last_p2pool_block_hash,
            ))
            current_work2.set(dict(
                timestamp=work.timestamp,
            ))
        
        print 'Searching for last p2pool-generated block...'
        yield get_real_work()
        print '    ...success!'
        print '    Matched block %x' % (current_work.value['last_p2pool_block_hash'],)
        print
        
        # setup worker logic
        
        merkle_root_to_transactions = expiring_dict.ExpiringDict(1000)
        
        def compute(state):
            generate_txn, shares = generate_transaction(
                last_p2pool_block_hash=state['last_p2pool_block_hash'],
                previous_node=state['highest_p2pool_share'],
                add_script=my_script,
                subsidy=50*100000000 >> state['height']//210000,
                nonce=random.randrange(2**64),
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
                print "Couldn't link returned work's merkle root with transactions - should only happen if you recently restarted p2pool"
                return False
            block = dict(header=header, txns=transactions)
            try:
                return p2pCallback(block)
            except:
                print
                print 'Error processing data received from worker:'
                traceback.print_exc()
                print
                return False
        
        # setup p2p logic and join p2pool network
        
        def share_node(node, ignore_peer=None):
            for peer in p2p_node.peers:
                if peer is ignore_peer:
                    continue
                peer.send_share(node.block)
            node.flag_shared()
        
        def p2pCallback(block, contact=None):
            hash_ = bitcoin_p2p.block_hash(block['header'])
            #print block
            if hash_ <= conv.bits_to_target(block['header']['bits']):
                print 'Got block! Passing to bitcoind!', hash_
                if factory.conn is not None:
                    factory.conn.addInv('block', block)
            
            node = Node(block)
            
            chain = chains.setdefault(node.chain_id(), Chain(node.chain_id()))
            res = chain.accept(node)
            if res == 'good':
                hash_data = bitcoin_p2p.HashType().pack(node.hash())
                for share_db in share_dbs:
                    share_db[hash_data] = node.block_data
                    share_db.sync()
                if chain is current_work.value['current_chain']:
                    print 'Accepted share, passing to peers. Hash: %x' % (node.hash(),)
                    share_node(node, contact)
                else:
                    print 'Accepted share to non-current chain. Hash: %x' % (node.hash(),)
            elif res == 'dup':
                print 'Got duplicate share, ignoring. Hash:', node.hash()
            elif res == 'orphan':
                print 'Got share referencing unknown share, requesting past shares from peer. Hash:', node.hash()
                contact.get_blocks(node.chain_id(), chain.highest.value[1].hash() if chain.highest.value[1] is not None else None) #.addErrback(lambda fail: None)
            else:
                raise ValueError('unknown result from chain.accept - %r' % (res,))
            
            w = dict(current_work.value)
            w['highest_p2pool_share'] = w['current_chain'].highest.value[1]
            current_work.set(w)
            
            return bitcoin_p2p.block_hash(block['header']) <= net.TARGET_MULTIPLIER*conv.bits_to_target(block['header']['bits'])
        
        @defer.inlineCallbacks
        def getBlocksCallback2(chain_id, highest, contact):
            chain = chains.setdefault(chain_id, Chain(chain_id))
            
            def get_down(node_hash):
                blocks = []
                while node_hash in chain.nodes:
                    node = chain.nodes[node_hash][1]
                    blocks.append(node_hash)
                    
                    node_hash = node.previous_hash()
                    if node_hash is None:
                        break
                return blocks
            
            blocks = get_down(chain.highest.value[1].hash())
            have = set(get_down(highest) if highest is not None else [])
            
            for block in reversed(blocks):
                if block in have:
                    continue
                contact.block(chain.nodes[block][1].block_data)
        
        def getBlocksCallback(chain_id, highest, contact):
            getBlocksCallback2(chain_id, highest, contact)
        
        port = {False: 9333, True: 19333}[args.testnet] if args.p2pool_port is None else args.p2pool_port
        print 'Joining p2pool network using TCP port %i...' % (port,)
        
        
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
            port=port,
            testnet=args.testnet, 
            addr_store=gdbm.open(os.path.join(os.path.dirname(__file__), 'peers.dat'), 'cs'),
            mode=1 if args.low_bandwidth else 0,
            preferred_addrs=map(parse, args.p2pool_nodes) + nodes,
        )
        p2p_node.handle_share = p2pCallback
        p2p_node.handle_get_blocks = getBlocksCallback
        
        p2p_node.start()
        
        # send nodes when the chain changes to their chain
        def work_changed(new_work):
            #print 'Work changed:', new_work
            for height, node in new_work['current_chain'].nodes.itervalues():
                if not node.shared:
                    print "Sharing node of switched to chain. Hash:", node.hash()
                    share_node(node)
        current_work.changed.watch(work_changed)
        
        print '    ...success!'
        print
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on port %i...' % (args.worker_port,)
        
        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response)))
        
        print '    ...success!'
        print
        
        # done!
        
        print 'Started successfully!'
        print
        
        while True:
            yield get_real_work()
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
    
    net = Testnet if args.testnet else Main
    
    reactor.callWhenRunning(main)
    reactor.run()
