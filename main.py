from __future__ import division

import argparse
import subprocess
import os
import sys
import traceback
import random

from twisted.internet import reactor, defer
from twisted.web import server

import jsonrpc
import conv
import worker_interface
import util
import bitcoin_p2p
import p2p
import expiring_dict

try:
    __version__ = subprocess.Popen(['svnversion', os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except IOError:
    __version__ = 'unknown'

name = 'p2pool (version %s)' % (__version__,)

parser = argparse.ArgumentParser(description=name)
parser.add_argument('--version', action='version', version=__version__)
parser.add_argument('-t', '--testnet',
    action='store_true', default=False, dest='testnet')

p2pool_group = parser.add_argument_group('p2pool interface')
p2pool_group.add_argument('-p', '--p2pool-port', metavar='PORT',
    help='use UDP port PORT to connect to other p2pool nodes and listen for connections (default: random)',
    type=int, action='store', default=None, dest='p2pool_port')
p2pool_group.add_argument('-n', '--p2pool-node', metavar='ADDR:PORT',
    help='connect to existing p2pool node at ADDR listening on UDP port PORT, in addition to builtin addresses',
    type=str, action='append', default=[], dest='p2pool_nodes')

worker_group = parser.add_argument_group('worker interface')
worker_group.add_argument('-w', '--worker-port', metavar='PORT',
    help='listen on PORT for RPC connections from miners asking for work and providing responses (default: 8338)',
    type=int, action='store', default=8338, dest='worker_port')

bitcoind_group = parser.add_argument_group('bitcoind interface')
bitcoind_group.add_argument('--bitcoind-address', metavar='BITCOIND_ADDRESS',
    help='connect to a bitcoind at this address (default: 127.0.0.1)',
    type=str, action='store', default='127.0.0.1', dest='bitcoind_address')
bitcoind_group.add_argument('--bitcoind-rpc-port', metavar='BITCOIND_RPC_PORT',
    help='connect to a bitcoind at this port over the RPC interface - used to get the current highest block via getwork (default: 8332)',
    type=int, action='store', default=8332, dest='bitcoind_rpc_port')
bitcoind_group.add_argument('--bitcoind-p2p-port', metavar='BITCOIND_P2P_PORT',
    help='connect to a bitcoind at this port over the p2p interface - used to submit blocks and get the pubkey to generate to via an IP transaction (default: 8333)',
    type=int, action='store', default=8333, dest='bitcoind_p2p_port')

bitcoind_group.add_argument(metavar='BITCOIND_RPC_USERNAME',
    help='bitcoind RPC interface username',
    type=str, action='store', dest='bitcoind_rpc_username')
bitcoind_group.add_argument(metavar='BITCOIND_RPC_PASSWORD',
    help='bitcoind RPC interface password',
    type=str, action='store', dest='bitcoind_rpc_password')

args = parser.parse_args()

# TARGET_MULTIPLIER needs to be less than the current difficulty to prevent miner clients from missing shares
if args.testnet:
    TARGET_MULTIPLIER = SPREAD = 32
    ROOT_BLOCK = 0x201e963d56e4becd1d8fc3fd72a53f23d80898cdacdabae2c4fde24
    SCRIPT = '410489175c7658845fd7c33d61029ebf4042e8386443ff6e6628fdb5ac938c31072dc61cee691ae1e8355c3a87cb4813cc9bf036fdb09078d35eacf9e9ab52374ebeac'.decode('hex')
    IDENTIFIER = 0x808330dc87e313b7
else:
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
        self.block_hash = bitcoin_p2p.block_hash(block['headers'])
        self.coinbase = coinbase_type.unpack(self.block['txns'][0]['tx_ins'][0]['script'], ignore_extra=True)
    
    def hash(self):
        return self.block_hash
    
    def previous_hash(self):
        hash_ = self.coinbase['previous_p2pool_share_hash']
        if hash_ == 2**256 - 1:
            return None
        return hash_
    
    def chain_id(self):
        return (self.coinbase['last_p2pool_block_hash'], self.block['headers']['bits'])
    
    def check(self, chain, height2, previous_node):
        # check bits and target
        if self.chain_id() != (chain.last_p2pool_block_hash, chain.bits):
            raise ValueError('wrong chain')
        if self.block_hash > TARGET_MULTIPLIER*conv.bits_to_target(chain.bits):
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

class Chain(object):
    def __init__(self, (last_p2pool_block_hash, bits)):
        self.last_p2pool_block_hash = last_p2pool_block_hash
        self.bits = bits
        
        self.nodes = {} # hash -> (height, node)
        self.highest = util.Variable((-1, None)) # (height, node) could be hash
        self.shared = set()
    
    def accept(self, node):
        # returns False if history is missing
        # returns True is ok
        # raises exception otherwise
        if node.chain_id() != (self.last_p2pool_block_hash, self.bits):
            raise ValueError('block does not belong to this chain')
        
        hash_ = node.hash()
        
        if hash_ in self.nodes:
            raise ValueError('already seen')
        
        previous_hash = node.previous_hash()
        
        if previous_hash is None:
            previous_height, previous_node = -1, None
        elif previous_hash not in self.nodes:
            return False
        else:
            previous_height, previous_node = self.nodes[previous_hash]
        
        height = previous_height + 1
        
        if not node.check(self, height, previous_node):
            raise ValueError('node check failed')
        
        self.nodes[hash_] = (height, node)
        
        if height > self.highest.value[0]:
            self.highest.set((height, node))
        
        return True

def generate_transaction(last_p2pool_block_hash, previous_node, add_script, subsidy, nonce):
    shares = (previous_node.shares[1:] if previous_node is not None else [SCRIPT]*SPREAD) + [add_script]
    
    dest_weights = {}
    for script in shares:
        dest_weights[script] = dest_weights.get(script, 0) + 1
    total_weight = sum(dest_weights.itervalues())
    
    amounts = dict((script, subsidy*weight*63//(64*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[SCRIPT] = amounts.get(SCRIPT, 0) + subsidy//64 # prevent fake previous p2pool blocks
    amounts[SCRIPT] = amounts.get(SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    print 'generate_transaction. height:', 0 if previous_node is None else previous_node.height2 + 1, 'amounts:', [x/100000000 for x in amounts.itervalues()]
    
    dests = sorted(amounts.iterkeys())
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=dict(index=4294967295, hash=0),
            sequence=4294967295,
            script=coinbase_type.pack(dict(
                identifier=IDENTIFIER,
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
        if block_hash == ROOT_BLOCK:
            defer.returnValue(block_hash)
        block = yield get_block(block_hash)
        coinbase_data = block['txns'][0]['tx_ins'][0]['script']
        try:
            coinbase = coinbase_type.unpack(coinbase_data, ignore_extra=True)
        except bitcoin_p2p.EarlyEnd:
            pass
        else:
            try:
                if coinbase['identifier'] == IDENTIFIER:
                    payouts = {}
                    for tx_out in block['txns'][0]['tx_outs']:
                        payouts[tx_out['script']] = payouts.get(tx_out['script'], 0) + tx_out['value']
                    subsidy = sum(payouts.itervalues())
                    if coinbase['subsidy'] == subsidy:
                        if payouts.get(SCRIPT, 0) >= subsidy//64:
                            defer.returnValue(block_hash)
            except Exception:
                print
                print "Error matching block:"
                print "block:", block
                traceback.print_exc()
                print
        block_hash = block['headers']['previous_block']

@defer.inlineCallbacks
def getwork(bitcoind):
    while True:
        try:
            getwork_df, height_df = bitcoind.rpc_getwork(), bitcoind.rpc_getblocknumber()
            getwork, height = conv.BlockAttempt.from_getwork((yield getwork_df)), (yield height_df)
        except:
            print
            print "Error getting work from bitcoind:"
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
                    print "Error getting payout script:"
                    print res
                    print
                    continue
                my_script = res['script']
            except:
                print
                print "Error getting payout script:"
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
        
        def work_changed(new_work):
            print "Work changed:", new_work
        current_work.changed.watch(work_changed)
        
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
            transactions = [generate_transaction(
                last_p2pool_block_hash=state['last_p2pool_block_hash'],
                previous_node=state['highest_p2pool_share'],
                add_script=my_script,
                subsidy=50*100000000 >> state['height']//210000,
                nonce=random.randrange(2**64),
            )[0]]
            merkle_root = bitcoin_p2p.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = transactions # will stay for 1000 seconds
            ba = conv.BlockAttempt(state['version'], state['previous_block'], merkle_root, current_work2.value['timestamp'], state['bits'])
            return ba.getwork(TARGET_MULTIPLIER)
        
        def got_response(data):
            # match up with transactions
            headers = conv.decode_data(data)
            transactions = merkle_root_to_transactions.get(headers['merkle_root'], None)
            if transactions is None:
                print "Couldn't link returned work's merkle root with transactions - should only happen if you recently restarted p2pool"
                return False
            block = dict(headers=headers, txns=transactions)
            try:
                return p2pCallback(block)
            except:
                print
                print "Error processing data received from worker:"
                traceback.print_exc()
                print
                return False
        
        # setup p2p logic and join p2pool network
        
        seen = set() # grows indefinitely!
        
        def p2pCallback(block, contact=None):
            hash_ = bitcoin_p2p.block_hash(block['headers'])
            #print block
            if hash_ <= conv.bits_to_target(block['headers']['bits']):
                print 'Got block! Passing to bitcoind!', hash_
                if factory.conn is not None:
                    factory.conn.addInv('block', block)
            
            node = Node(block)
            
            if chains.setdefault(node.chain_id(), Chain(node.chain_id())).accept(node):
                print 'Accepted share, passing to peers. Hash: %x' % (node.hash(),)
                block_data = bitcoin_p2p.block.pack(block)
                for peer in p2p_node.peers:
                    if peer is contact:
                        continue
                    peer.block(block_data)
            else:
                print 'Got share referencing unknown share, requesting past shares from peer', node.hash()
                contact.get_blocks(node.chain_id())
            
            w = dict(current_work.value)
            w['highest_p2pool_share'] = w['current_chain'].highest.value[1]
            current_work.set(w)
            
            return bitcoin_p2p.block_hash(block['headers']) <= TARGET_MULTIPLIER*conv.bits_to_target(block['headers']['bits'])
        
        def getBlocksCallback(chain_id, contact):
            for height, node in reversed(chains.setdefault(chain_id, Chain(chain_id)).nodes.itervalues()): # XXX
                contact.block(bitcoin_p2p.block.pack(node.block))
        
        port = random.randrange(49152, 65536) if args.p2pool_port is None else args.p2pool_port
        print 'Joining p2pool network using UDP port %i...' % (port,)
        
        p2p_node = p2p.Node(p2pCallback, getBlocksCallback, udpPort=port)
        def parse(x):
            ip, port = x.split(':')
            return ip, int(port)
        
        nodes = [('72.14.191.28', 21519)] # XXX
        p2p_node.joinNetwork(map(parse, args.p2pool_nodes) + nodes)
        yield p2p_node._joinDeferred
        p2p_node.printContacts()
        
        print '    ...success!'
        print
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on port %i...' % (args.worker_port,)
        
        yield reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response)))
        
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
        print "Fatal error:"
        traceback.print_exc()
        print
        reactor.stop()

reactor.callWhenRunning(main)
reactor.run()
