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
    if not net.VERSION_CHECK((yield bitcoind.rpc_getinfo())['version']):
        print >>sys.stderr, '    Bitcoin version too old! Upgrade to 0.6.4 or newer!'
        raise deferral.RetrySilentlyException()

@deferral.retry('Error getting work from bitcoind:', 3)
@defer.inlineCallbacks
def getwork(bitcoind, use_getblocktemplate=False):
    def go():
        if use_getblocktemplate:
            return bitcoind.rpc_getblocktemplate(dict(mode='template'))
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
    packed_transactions = [(x['data'] if isinstance(x, dict) else x).decode('hex') for x in work['transactions']]
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
    if bitcoind_work.value['use_getblocktemplate']:
        try:
            result = yield bitcoind.rpc_submitblock(bitcoin_data.block_type.pack(block).encode('hex'))
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
