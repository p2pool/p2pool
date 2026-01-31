import sys
import time

from twisted.internet import defer

import p2pool
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, jsonrpc
txlookup = {}

# Global broadcaster instance (initialized by main.py)
_broadcaster = None

def set_broadcaster(broadcaster):
    """Set the global broadcaster instance for multi-peer propagation"""
    global _broadcaster
    print 'Helper: Broadcaster instance registered for multi-peer propagation'
    _broadcaster = broadcaster

def get_broadcaster():
    """Get the global broadcaster instance"""
    return _broadcaster

def get_broadcaster_status():
    """Get broadcaster status for web dashboard"""
    if _broadcaster:
        return _broadcaster.get_network_status()
    else:
        return {
            'enabled': False,
            'health': {'healthy': False, 'active_connections': 0},
            'message': 'Multi-peer broadcaster disabled'
        }

@deferral.retry('Error while checking Bitcoin connection:', 1)
@defer.inlineCallbacks
def check(coind, net, args):
    if not (yield net.PARENT.RPC_CHECK(coind)):
        print >>sys.stderr, "    Check failed! Make sure that you're connected to the right coind with --coind-rpc-port, and that it has finished syncing!"
        raise deferral.RetrySilentlyException()
    
    version_check_result = net.VERSION_CHECK((yield coind.rpc_getnetworkinfo())['version'])
    if version_check_result == True: version_check_result = None # deprecated
    if version_check_result == False: version_check_result = 'Coin daemon too old! Upgrade!' # deprecated
    if version_check_result is not None:
        print >>sys.stderr, '    ' + version_check_result
        raise deferral.RetrySilentlyException()
    
    try:
        blockchaininfo = yield coind.rpc_getblockchaininfo()
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
        if not args.allow_obsolete_coind:
            print "\nIf you know what you're doing, this error may be overridden by running p2pool"
            print "with the '--allow-obsolete-coind' command-line option.\n\n\n"
            raise deferral.RetrySilentlyException()

@deferral.retry('Error getting work from coind:', 3)
@defer.inlineCallbacks
def getwork(coind, net, use_getblocktemplate=False, txidcache={}, feecache={}, feefifo=[], known_txs={}):
    def go():
        if use_getblocktemplate:
            return coind.rpc_getblocktemplate(dict(mode='template', rules=['segwit','mweb'] if 'mweb' in getattr(net, 'SOFTFORKS_REQUIRED', set()) else ['segwit']))
        else:
            return coind.rpc_getmemorypool()
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
    txfees = []
    cachehits = 0
    cachemisses = 0
    knownhits = 0
    knownmisses = 0
    skipped_mweb = 0
    for x in work['transactions']:
        fee = x['fee']
        x = x['data'] if isinstance(x, dict) else x
        packed = None
        if x in txidcache:
            cachehits += 1
            txid = (txidcache[x])
        else:
            cachemisses += 1
            packed = x.decode('hex')
            txid = bitcoin_data.hash256(packed)
            txidcache[x] = txid
        if txid in known_txs:
            knownhits += 1
            unpacked = known_txs[txid]
        else:
            knownmisses += 1
            if not packed:
                packed = x.decode('hex')
            try:
                unpacked = bitcoin_data.tx_type.unpack(packed)
            except Exception as e:
                # Transaction parsing failed - likely MWEB (MimbleWimble Extension Block)
                # transaction on Litecoin. These use a different format that p2pool
                # doesn't yet support.
                #
                # MWEB transactions have a special structure that includes confidential
                # transaction data (Pedersen commitments, range proofs, etc.) which
                # our standard Bitcoin tx parser cannot decode.
                #
                # TODO: Implement proper MWEB transaction parsing support
                # See: https://github.com/litecoin-project/lips/blob/master/lip-0002.mediawiki
                #
                # For now, store as a "raw" transaction wrapper so share broadcasting works.
                # This allows the transaction to exist in known_txs for P2P share propagation.
                skipped_mweb += 1
                if skipped_mweb == 1:  # Only print once per batch
                    print '[MWEB] Detected MWEB/MimbleWimble transaction(s) - full parsing not yet implemented'
                    print '[MWEB] Storing as raw bytes for P2P share propagation (fee calculation unavailable)'
                # Create a raw transaction wrapper that stores the packed bytes
                # This allows the tx to be in known_txs for share broadcasting
                unpacked = {'_raw_tx': packed, '_raw_size': len(packed), '_mweb': True}
        # Add to lists (including MWEB transactions stored as raw)
        txhashes.append(txid)
        unpacked_transactions.append(unpacked)
        txfees.append(fee)
        # The only place where we can get information on transaction fees is in GBT results, so we need to store those
        # for a while so we can spot shares that miscalculate the block reward
        if not txid in feecache:
            feecache[txid] = fee
            feefifo.append(txid)
    
    if skipped_mweb > 0:
        print '[MWEB] Processed %d MWEB/MimbleWimble transaction(s) as raw bytes' % skipped_mweb
        print '[MWEB] TODO: Implement full MWEB parsing for fee estimation (see LIP-0002)'

    if time.time() - txidcache['start'] > 30*60.:
        keepers = {(x['data'] if isinstance(x, dict) else x):txid for x, txid in zip(work['transactions'], txhashes)}
        txidcache.clear()
        txidcache.update(keepers)
        # limit the fee cache to 100,000 entries, which should be about 10-20 MB
        fum = 100000
        while len(feefifo) > fum:
            del feecache[feefifo.pop(0)]
    if 'height' not in work:
        work['height'] = (yield coind.rpc_getblock(work['previousblockhash']))['height'] + 1
    elif p2pool.DEBUG:
        assert work['height'] == (yield coind.rpc_getblock(work['previousblockhash']))['height'] + 1

    t1 = time.time()
    if p2pool.BENCH: print "%8.3f ms for helper.py:getwork(). Cache: %i hits %i misses, %i known_tx %i unknown %i cached" % ((t1 - t0)*1000., cachehits, cachemisses, knownhits, knownmisses, len(txidcache))
    defer.returnValue(dict(
        version=work['version'],
        previous_block=int(work['previousblockhash'], 16),
        transactions=unpacked_transactions,
        transaction_hashes=txhashes,
        transaction_fees=txfees,
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
        print >>sys.stderr, 'No coind connection when block submittal attempted! %s%064x' % (net.PARENT.BLOCK_EXPLORER_URL_PREFIX, bitcoin_data.hash256(bitcoin_data.block_header_type.pack(block['header'])))
        raise deferral.RetrySilentlyException()
    factory.conn.value.send_block(block=block)

@deferral.retry('Error submitting block: (will retry)', 10, 10)
@defer.inlineCallbacks
def submit_block_rpc(block, ignore_failure, coind, coind_work, net):
    segwit_rules = set(['!segwit', 'segwit'])
    segwit_activated = len(segwit_rules - set(coind_work.value['rules'])) < len(segwit_rules)
    if coind_work.value['use_getblocktemplate']:
        try:
            result = yield coind.rpc_submitblock((bitcoin_data.block_type if segwit_activated else bitcoin_data.stripped_block_type).pack(block).encode('hex') + coind_work.value['mweb'])
        except jsonrpc.Error_for_code(-32601): # Method not found, for older litecoin versions
            result = yield coind.rpc_getblocktemplate(dict(mode='submit', data=bitcoin_data.block_type.pack(block).encode('hex')))
        success = result is None
    else:
        result = yield coind.rpc_getmemorypool(bitcoin_data.block_type.pack(block).encode('hex'))
        success = result
    success_expected = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(block['header'])) <= block['header']['bits'].target
    if (not success and success_expected and not ignore_failure) or (success and not success_expected):
        print >>sys.stderr, 'Block submittal result: %s (%r) Expected: %s' % (success, result, success_expected)

def submit_block(block, ignore_failure, node, broadcaster=None):
    """Submit block via P2P and RPC, optionally with parallel broadcast
    
    Args:
        block: Block dict to submit
        ignore_failure: If True, ignore RPC failures
        node: Node object with factory, bitcoind, etc.
        broadcaster: Optional NetworkBroadcaster for parallel propagation
    
    Returns:
        Deferred from RPC submission
    """
    # Always submit via local P2P first (fastest path)
    submit_block_p2p(block, node.factory, node.net)
    
    # If broadcaster available, do parallel broadcast to additional peers
    if broadcaster is not None:
        # Fire and forget - don't block on broadcast completion
        # The local P2P submission is the critical path
        d = broadcaster.broadcast_block(block)
        d.addErrback(lambda f: sys.stderr.write('Broadcaster error: %s\n' % f.getErrorMessage()))
    
    # Submit via RPC for verification
    return submit_block_rpc(block, ignore_failure, node.bitcoind, node.bitcoind_work, node.net)

@defer.inlineCallbacks
def check_block_header(coind, block_hash):
    try:
        yield coind.rpc_getblockheader(block_hash)
    except jsonrpc.Error_for_code(-5):
        defer.returnValue(False)
    else:
        defer.returnValue(True)
