import sys
import time

from twisted.internet import defer

import p2pool
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, jsonrpc

@deferral.retry('Error while checking Bitcoin connection:', 1)
@defer.inlineCallbacks
def check(bitcoind, net):
    if not (yield net.PARENT.RPC_CHECK(bitcoind)):
        print >>sys.stderr, "    Check failed! Make sure that you're connected to the right bitcoind with --bitcoind-rpc-port!"
        raise deferral.RetrySilentlyException()
    
    version_check_result = net.VERSION_CHECK((yield bitcoind.rpc_getnetworkinfo())['version'])
    if version_check_result == True: version_check_result = None # deprecated
    if version_check_result == False: version_check_result = 'Coin daemon too old! Upgrade!' # deprecated
    if version_check_result is not None:
        print >>sys.stderr, '    ' + version_check_result
        raise deferral.RetrySilentlyException()
    
    try:
        blockchaininfo = yield bitcoind.rpc_getblockchaininfo()
        softforks_supported = set(item['id'] for item in blockchaininfo.get('softforks', []))
        try:
            softforks_supported |= set(item['id'] for item in blockchaininfo.get('bip9_softforks', []))
        except TypeError: # https://github.com/bitcoin/bitcoin/pull/7863
            softforks_supported |= set(item for item in blockchaininfo.get('bip9_softforks', []))
    except jsonrpc.Error_for_code(-32601): # Method not found
        softforks_supported = set()
    if getattr(net, 'SOFTFORKS_REQUIRED', set()) - softforks_supported:
        print 'Coin daemon too old! Upgrade!'
        raise deferral.RetrySilentlyException()

@deferral.retry('Error getting work from bitcoind:', 3)
@defer.inlineCallbacks
def getwork(bitcoind, use_getblocktemplate=False):
    def go():
        if use_getblocktemplate:
            return bitcoind.rpc_getblocktemplate(dict(mode='template', rules=['segwit']))
        else:
            return bitcoind.rpc_getmemorypool()
    try:
        start = time.time()
        work = yield go()
        end = time.time()
    except jsonrpc.Error_for_code(-32601): # Method not found
        use_getblocktemplate = not use_getblocktemplate
        try:
            start = time.time()
            work = yield go()
            end = time.time()
        except jsonrpc.Error_for_code(-32601): # Method not found
            print >>sys.stderr, 'Error: Bitcoin version too old! Upgrade to v0.5 or newer!'
            raise deferral.RetrySilentlyException()
    packed_transactions = [x['data'].decode('hex') for x in work['transactions'] if len(x.get('depends', [])) == 0]
    if 'height' not in work:
        work['height'] = (yield bitcoind.rpc_getblock(work['previousblockhash']))['height'] + 1
    elif p2pool.DEBUG:
        assert work['height'] == (yield bitcoind.rpc_getblock(work['previousblockhash']))['height'] + 1
    defer.returnValue(dict(
        version=work['version'],
        previous_block=int(work['previousblockhash'], 16),
        transactions=map(bitcoin_data.tx_type.unpack, packed_transactions),
        transaction_hashes=map(bitcoin_data.hash256, packed_transactions),
        transaction_fees=[x.get('fee', None) if isinstance(x, dict) else None for x in work['transactions']],
        subsidy=work['coinbasevalue'],
        time=work['time'] if 'time' in work else work['curtime'],
        bits=bitcoin_data.FloatingIntegerType().unpack(work['bits'].decode('hex')[::-1]) if isinstance(work['bits'], (str, unicode)) else bitcoin_data.FloatingInteger(work['bits']),
        coinbaseflags=work['coinbaseflags'].decode('hex') if 'coinbaseflags' in work else ''.join(x.decode('hex') for x in work['coinbaseaux'].itervalues()) if 'coinbaseaux' in work else '',
        height=work['height'],
        rules=work.get('rules', []),
        last_update=time.time(),
        use_getblocktemplate=use_getblocktemplate,
        latency=end - start,
    ))

@deferral.retry('Error submitting primary block: (will retry)', 10, 10)
def submit_block_p2p(block, factory, net):
    if factory.conn.value is None:
        print >>sys.stderr, 'No bitcoind connection when block submittal attempted! %s%064x' % (net.PARENT.BLOCK_EXPLORER_URL_PREFIX, bitcoin_data.hash256(bitcoin_data.block_header_type.pack(block['header'])))
        raise deferral.RetrySilentlyException()
    factory.conn.value.send_block(block=block)

@deferral.retry('Error submitting block: (will retry)', 10, 10)
@defer.inlineCallbacks
def submit_block_rpc(block, ignore_failure, bitcoind, bitcoind_work, net):
    segwit_rules = set(['!segwit', 'segwit'])
    segwit_activated = len(segwit_rules - set(bitcoind_work.value['rules'])) < len(segwit_rules)
    if bitcoind_work.value['use_getblocktemplate']:
        try:
            result = yield bitcoind.rpc_submitblock((bitcoin_data.block_type if segwit_activated else bitcoin_data.stripped_block_type).pack(block).encode('hex'))
        except jsonrpc.Error_for_code(-32601): # Method not found, for older litecoin versions
            result = yield bitcoind.rpc_getblocktemplate(dict(mode='submit', data=bitcoin_data.block_type.pack(block).encode('hex')))
        success = result is None
    else:
        result = yield bitcoind.rpc_getmemorypool(bitcoin_data.block_type.pack(block).encode('hex'))
        success = result
    success_expected = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(block['header'])) <= block['header']['bits'].target
    if (not success and success_expected and not ignore_failure) or (success and not success_expected):
        print >>sys.stderr, 'Block submittal result: %s (%r) Expected: %s' % (success, result, success_expected)

def submit_block(block, ignore_failure, factory, bitcoind, bitcoind_work, net):
    submit_block_p2p(block, factory, net)
    submit_block_rpc(block, ignore_failure, bitcoind, bitcoind_work, net)

@defer.inlineCallbacks
def check_genesis_block(bitcoind, genesis_block_hash):
    try:
        yield bitcoind.rpc_getblock(genesis_block_hash)
    except jsonrpc.Error_for_code(-5):
        defer.returnValue(False)
    else:
        defer.returnValue(True)
