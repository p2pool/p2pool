import sys
import time

from twisted.internet import defer

import p2pool
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, jsonrpc
txlookup = {}

@deferral.retry('Error while checking Bitcoin connection:', 1)
@defer.inlineCallbacks
def check(bitcoind, net, args):
    if not (yield net.PARENT.RPC_CHECK(bitcoind)):
        print >>sys.stderr, "    Check failed! Make sure that you're connected to the right bitcoind with --bitcoind-rpc-port, and that it has finished syncing!"
        raise deferral.RetrySilentlyException()
    
    version_check_result = net.VERSION_CHECK((yield bitcoind.rpc_getnetworkinfo())['version'])
    if version_check_result == True: version_check_result = None # deprecated
    if version_check_result == False: version_check_result = 'Coin daemon too old! Upgrade!' # deprecated
    if version_check_result is not None:
        print >>sys.stderr, '    ' + version_check_result
        raise deferral.RetrySilentlyException()
    
    try:
        blockchaininfo = yield bitcoind.rpc_getblockchaininfo()
        try:
            softforks_supported = set(item['id'] for item in blockchaininfo.get('softforks', [])) # not working with 0.19.0.1
        except TypeError:
            softforks_supported = set(item for item in blockchaininfo.get('softforks', [])) # fix for https://github.com/jtoomim/p2pool/issues/38
        try:
            softforks_supported |= set(item['id'] for item in blockchaininfo.get('bip9_softforks', []))
        except TypeError: # https://github.com/bitcoin/bitcoin/pull/7863
            softforks_supported |= set(item for item in blockchaininfo.get('bip9_softforks', []))
    except jsonrpc.Error_for_code(-32601): # Method not found
        softforks_supported = set()
    unsupported_forks = getattr(net, 'SOFTFORKS_REQUIRED', set()) - softforks_supported
    if unsupported_forks:
        print "You are running a coin daemon that does not support all of the "
        print "forking features that have been activated on this blockchain."
        print "Consequently, your node may mine invalid blocks or may mine blocks that"
        print "are not part of the Nakamoto consensus blockchain.\n"
        print "Missing fork features:", ', '.join(unsupported_forks)
        if not args.allow_obsolete_bitcoind:
            print "\nIf you know what you're doing, this error may be overridden by running p2pool"
            print "with the '--allow-obsolete-bitcoind' command-line option.\n\n\n"
            raise deferral.RetrySilentlyException()

@deferral.retry('Error getting work from bitcoind:', 3)
@defer.inlineCallbacks
def getwork(bitcoind, net, use_getblocktemplate=False, txidcache={}, feecache={}, feefifo=[], known_txs={}):
    def go():
        if use_getblocktemplate:
            return bitcoind.rpc_getblocktemplate(dict(mode='template', rules=['segwit','mweb'] if 'mweb' in getattr(net, 'SOFTFORKS_REQUIRED', set()) else ['segwit']))
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

    if not 'start' in txidcache: # we clear it every 30 min
        txidcache['start'] = time.time()

    t0 = time.time()
    unpacked_transactions = []
    txhashes = []
    cachehits = 0
    cachemisses = 0
    knownhits = 0
    knownmisses = 0
    for x in work['transactions']:
        fee = x['fee']
        x = x['data'] if isinstance(x, dict) else x
        packed = None
        if x in txidcache:
            cachehits += 1
            txid = (txidcache[x])
            txhashes.append(txid)
        else:
            cachemisses += 1
            packed = x.decode('hex')
            txid = bitcoin_data.hash256(packed)
            txidcache[x] = txid
            txhashes.append(txid)
        if txid in known_txs:
            knownhits += 1
            unpacked = known_txs[txid]
        else:
            knownmisses += 1
            if not packed:
                packed = x.decode('hex')
            unpacked = bitcoin_data.tx_type.unpack(packed)
        unpacked_transactions.append(unpacked)
        # The only place where we can get information on transaction fees is in GBT results, so we need to store those
        # for a while so we can spot shares that miscalculate the block reward
        if not txid in feecache:
            feecache[txid] = fee
            feefifo.append(txid)

    if time.time() - txidcache['start'] > 30*60.:
        keepers = {(x['data'] if isinstance(x, dict) else x):txid for x, txid in zip(work['transactions'], txhashes)}
        txidcache.clear()
        txidcache.update(keepers)
        # limit the fee cache to 100,000 entries, which should be about 10-20 MB
        fum = 100000
        while len(feefifo) > fum:
            del feecache[feefifo.pop(0)]
    if 'height' not in work:
        work['height'] = (yield bitcoind.rpc_getblock(work['previousblockhash']))['height'] + 1
    elif p2pool.DEBUG:
        assert work['height'] == (yield bitcoind.rpc_getblock(work['previousblockhash']))['height'] + 1

    t1 = time.time()
    if p2pool.BENCH: print "%8.3f ms for helper.py:getwork(). Cache: %i hits %i misses, %i known_tx %i unknown %i cached" % ((t1 - t0)*1000., cachehits, cachemisses, knownhits, knownmisses, len(txidcache))
    defer.returnValue(dict(
        version=work['version'],
        previous_block=int(work['previousblockhash'], 16),
        transactions=unpacked_transactions,
        transaction_hashes=txhashes,
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
        mweb='01' + work['mweb'] if 'mweb' in work else '',
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
            result = yield bitcoind.rpc_submitblock((bitcoin_data.block_type if segwit_activated else bitcoin_data.stripped_block_type).pack(block).encode('hex') + bitcoind_work.value['mweb'])
        except jsonrpc.Error_for_code(-32601): # Method not found, for older litecoin versions
            result = yield bitcoind.rpc_getblocktemplate(dict(mode='submit', data=bitcoin_data.block_type.pack(block).encode('hex')))
        success = result is None
    else:
        result = yield bitcoind.rpc_getmemorypool(bitcoin_data.block_type.pack(block).encode('hex'))
        success = result
    success_expected = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(block['header'])) <= block['header']['bits'].target
    if (not success and success_expected and not ignore_failure) or (success and not success_expected):
        print >>sys.stderr, 'Block submittal result: %s (%r) Expected: %s' % (success, result, success_expected)

def submit_block(block, ignore_failure, node):
    submit_block_p2p(block, node.factory, node.net)
    submit_block_rpc(block, ignore_failure, node.bitcoind, node.bitcoind_work,
                     node.net)

@defer.inlineCallbacks
def check_block_header(bitcoind, block_hash):
    try:
        yield bitcoind.rpc_getblockheader(block_hash)
    except jsonrpc.Error_for_code(-5):
        defer.returnValue(False)
    else:
        defer.returnValue(True)
