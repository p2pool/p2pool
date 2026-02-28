import sys
import time

from twisted.internet import defer, error as twisted_error

import p2pool
from p2pool.dash import data as dash_data
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, jsonrpc

@deferral.retry('Error while checking dash connection:', 1)
@defer.inlineCallbacks
def check(coind, net):
    if not (yield net.PARENT.RPC_CHECK(coind)):
        print >>sys.stderr, "    Check failed! Make sure that you're connected to the right coind with --coind-rpc-port!"
        raise deferral.RetrySilentlyException()
    if not net.VERSION_CHECK((yield coind.rpc_getnetworkinfo())['version']):
        print >>sys.stderr, '    dash version too old! Upgrade to v20.0.0 or newer!'
        raise deferral.RetrySilentlyException()

@deferral.retry('Error getting work from coind:', 3)
@defer.inlineCallbacks
def getwork(coind, net, use_getblocktemplate=True):
    def go():
        if use_getblocktemplate:
            # Add Segwit/MWEB rules based on network's required softforks
            rules = []
            if 'segwit' in getattr(net, 'SOFTFORKS_REQUIRED', set()):
                rules.append('segwit')
            if 'mweb' in getattr(net, 'SOFTFORKS_REQUIRED', set()):
                rules.append('mweb')
            return coind.rpc_getblocktemplate(dict(mode='template', rules=rules) if rules else dict(mode='template'))
        else:
            return coind.rpc_getmemorypool()
    try:
        start = time.time()
        work = yield go()
        end = time.time()
    except twisted_error.TimeoutError:
        print >>sys.stderr, '    coind RPC timeout - coind may be busy or overloaded, retrying...'
        raise deferral.RetrySilentlyException()
    except twisted_error.ConnectionRefusedError:
        print >>sys.stderr, '    coind connection refused - is coind running?'
        raise deferral.RetrySilentlyException()
    except jsonrpc.Error_for_code(-10): # Initial sync
        print >>sys.stderr, '    Dash Core is in initial sync, waiting for blocks...'
        raise deferral.RetrySilentlyException()
    except jsonrpc.Error_for_code(-32601): # Method not found
        use_getblocktemplate = not use_getblocktemplate
        try:
            start = time.time()
            work = yield go()
            end = time.time()
        except jsonrpc.Error_for_code(-32601): # Method not found
            print >>sys.stderr, 'Error: dash version too old! Upgrade to v20.0.0 or newer!'
            raise deferral.RetrySilentlyException()
    except jsonrpc.Error, e:
        # Catch any other JSON-RPC errors and handle them gracefully
        try:
            error_msg = str(e)
        except:
            error_msg = 'JSON-RPC error (code: %s)' % getattr(e, 'code', 'unknown')
        print >>sys.stderr, '    coind RPC error: %s' % error_msg
        raise deferral.RetrySilentlyException()

    # Include ALL transactions from getblocktemplate
    # Per BIP 22, transactions are already ordered with dependencies before dependents
    packed_transactions = []
    for x in work.get('transactions', []):
        if isinstance(x, dict):
            packed_transactions.append(x['data'].decode('hex'))
        else:
            packed_transactions.append(x.decode('hex'))

    if 'height' not in work:
        work['height'] = (yield coind.rpc_getblock(work['previousblockhash']))['height'] + 1
    elif p2pool.DEBUG:
        assert work['height'] == (yield coind.rpc_getblock(work['previousblockhash']))['height'] + 1

    # Dash Payments
    packed_payments = []
    payment_amount = 0

    payment_objects = []
    if 'masternode' in work:
        if isinstance(work['masternode'], list):
            payment_objects += work['masternode']
        else:
            payment_objects += [work['masternode']]
    if 'superblock' in work:
        payment_objects += work['superblock']

    for obj in payment_objects:
        g={}
        # Always count the amount towards payment_amount, even if payee/script is missing
        if 'amount' in obj and obj['amount'] > 0:
            payment_amount += obj['amount']
            g['amount'] = obj['amount']
            # Use 'payee' if available (regular masternode address)
            # For script-only payments (like platform OP_RETURN), encode the script
            # with '!' prefix so it survives serialization (minimal overhead)
            if 'payee' in obj and obj['payee']:
                # Regular payment with address
                g['payee'] = str(obj['payee'])
                packed_payments.append(g)
            elif 'script' in obj and obj['script']:
                # Script-only payment (e.g., platform OP_RETURN with empty payee)
                # Encode script as "!<hex>" - '!' prefix not in base58, minimal overhead
                g['payee'] = '!' + obj['script']
                packed_payments.append(g)

    coinbase_payload = None
    if 'coinbase_payload' in work and len(work['coinbase_payload']) != 0:
        coinbase_payload = work['coinbase_payload'].decode('hex')

    # Use bitcoin_data for networks with Segwit support (Litecoin, etc.)
    # Use dash_data for Dash-specific networks
    data_module = bitcoin_data if 'segwit' in getattr(net, 'SOFTFORKS_REQUIRED', set()) else dash_data

    defer.returnValue(dict(
        version=work['version'],
        previous_block=int(work['previousblockhash'], 16),
        transactions=map(data_module.tx_type.unpack, packed_transactions),
        transaction_hashes=map(data_module.hash256, packed_transactions),
        transaction_fees=[x.get('fee', None) if isinstance(x, dict) else None for x in work['transactions']],
        subsidy=work['coinbasevalue'],
        time=work['time'] if 'time' in work else work['curtime'],
        bits=data_module.FloatingIntegerType().unpack(work['bits'].decode('hex')[::-1]) if isinstance(work['bits'], (str, unicode)) else data_module.FloatingInteger(work['bits']),
        coinbaseflags=work['coinbaseflags'].decode('hex') if 'coinbaseflags' in work else ''.join(x.decode('hex') for x in work['coinbaseaux'].itervalues()) if 'coinbaseaux' in work else '',
        height=work['height'],
        last_update=time.time(),
        use_getblocktemplate=use_getblocktemplate,
        latency=end - start,
        payment_amount = payment_amount,
        packed_payments = packed_payments,
        coinbase_payload = coinbase_payload,
    ))

@deferral.retry('Error submitting primary block: (will retry)', 10, 10)
def submit_block_p2p(block, factory, net):
    """Submit found block via Dash P2P network for fast propagation."""
    block_hash = dash_data.hash256(dash_data.block_header_type.pack(block['header']))
    
    if factory.conn.value is None:
        print >>sys.stderr, 'No coind P2P connection when block submittal attempted! %s%064x' % (net.PARENT.BLOCK_EXPLORER_URL_PREFIX, block_hash)
        raise deferral.RetrySilentlyException()
    
    # Serialize and send block
    try:
        print 'P2P: Sending block %064x to coind via P2P protocol...' % block_hash
        print 'P2P: Block header version: %d, prev: %064x' % (block['header']['version'], block['header']['previous_block'])
        print 'P2P: Block has %d transactions' % len(block.get('txs', []))
        factory.conn.value.send_block(block=block)
        print 'P2P: Block sent successfully to coind for network propagation'
    except Exception as e:
        print >>sys.stderr, 'P2P: ERROR sending block: %s' % e
        raise

@deferral.retry('Error submitting block: (will retry)', 10, 10)
@defer.inlineCallbacks
def submit_block_rpc(block, ignore_failure, coind, coind_work, net):
    block_hash = dash_data.hash256(dash_data.block_header_type.pack(block['header']))
    pow_hash = net.PARENT.POW_FUNC(dash_data.block_header_type.pack(block['header']))
    block_height = block['header'].get('height', 'unknown')
    
    print ''
    print '=' * 70
    print 'BLOCK SUBMISSION STARTED at %s' % time.strftime('%Y-%m-%d %H:%M:%S')
    print '  Block hash:   %064x' % block_hash
    print '  POW hash:     %064x' % pow_hash
    print '  Target:       %064x' % block['header']['bits'].target
    print '  Prev block:   %064x' % block['header']['previous_block']
    print '  Transactions: %d' % len(block.get('txs', []))
    print '=' * 70
    
    result = None
    success = False
    p2p_won_race = False
    
    if coind_work.value['use_getblocktemplate']:
        try:
            block_data = dash_data.block_type.pack(block).encode('hex')
            print 'RPC: Calling submitblock with %d bytes of data...' % len(block_data)
            result = yield coind.rpc_submitblock(block_data)
            print 'RPC: submitblock returned: %r' % result
        except jsonrpc.Error_for_code(-32601): # Method not found, for older litecoin versions
            result = yield coind.rpc_getblocktemplate(dict(mode='submit', data=dash_data.block_type.pack(block).encode('hex')))
        except Exception as e:
            print >>sys.stderr, 'RPC: submitblock ERROR: %s' % e
            raise
        # submitblock returns None on success, "duplicate" if block already known (P2P won the race!)
        # Other return values indicate errors: "inconclusive", "rejected", etc.
        success = result is None or result == 'duplicate'
        p2p_won_race = result == 'duplicate'
        
        # Check for specific error conditions
        if result is not None and result != 'duplicate':
            print >>sys.stderr, '*** WARNING: submitblock returned error: %r ***' % result
            if 'inconclusive' in str(result).lower():
                print >>sys.stderr, '    Block submission was inconclusive - may or may not be accepted'
            elif 'rejected' in str(result).lower():
                print >>sys.stderr, '    Block was REJECTED by the network!'
            elif 'bad-prevblk' in str(result).lower():
                print >>sys.stderr, '    Block has invalid previous block - chain may have moved!'
            elif 'stale' in str(result).lower():
                print >>sys.stderr, '    Block is STALE - another block was found first!'
    else:
        result = yield coind.rpc_getmemorypool(dash_data.block_type.pack(block).encode('hex'))
        success = result
        p2p_won_race = False
    success_expected = pow_hash <= block['header']['bits'].target
    
    print 'BLOCK SUBMISSION RESULT (RPC):'
    if p2p_won_race:
        print '  *** P2P WON THE RACE! Block already propagated via P2P network ***'
        print '  RPC result: %s (this is expected when P2P submits first)' % str(result)
        print '  SUCCESS: Block was accepted!'
    else:
        print '  RPC accepted: %s (result: %s)' % (success, str(result))
    print '  Expected success: %s' % success_expected
    
    if (not success and success_expected and not ignore_failure) or (success and not success_expected):
        print >>sys.stderr, 'Block submittal result: %s (%r) Expected: %s' % (success, result, success_expected)
    
    # Check chainlock status after submission (but skip if P2P already submitted it)
    if success and not p2p_won_race:
        yield check_block_chainlock(coind, block_hash, net)

@defer.inlineCallbacks
def submit_block(block, ignore_failure, factory, coind, coind_work, net):
    """Submit block via both P2P and RPC for redundant propagation."""
    # Submit via P2P first for fastest network propagation (synchronous)
    submit_block_p2p(block, factory, net)
    # Also submit via RPC (submitblock call) and wait for result
    yield submit_block_rpc(block, ignore_failure, coind, coind_work, net)

@defer.inlineCallbacks
def check_block_header(bitcoind, block_hash):
    try:
        yield bitcoind.rpc_getblockheader(block_hash)
    except jsonrpc.Error_for_code(-5):
        defer.returnValue(False)
    else:
        defer.returnValue(True)

@defer.inlineCallbacks
def check_block_chainlock(coind, block_hash, net):
    """Check and log the chainlock status of a submitted block."""
    from twisted.internet import reactor
    
    # Skip chainlock check for regtest - no masternodes/chainlocks
    parent_name = getattr(net.PARENT, 'NAME', '') if hasattr(net, 'PARENT') else ''
    if 'regtest' in parent_name.lower():
        print 'CHAINLOCK CHECK: Skipped (regtest mode has no chainlocks)'
        defer.returnValue(None)
    
    # Also skip if network doesn't have chainlocks explicitly disabled
    if hasattr(net, 'CHAINLOCK_ENABLED') and not net.CHAINLOCK_ENABLED:
        print 'CHAINLOCK CHECK: Skipped (chainlocks disabled for this network)'
        defer.returnValue(None)
    
    # Wait a few seconds for block to propagate
    for delay in [2, 5, 10, 30, 60]:
        yield deferral.sleep(delay)
        try:
            block_info = yield coind.rpc_getblock('%064x' % block_hash)
            chainlock = block_info.get('chainlock', False)
            confirmations = block_info.get('confirmations', 0)
            height = block_info.get('height', 'unknown')
            
            print ''
            print 'CHAINLOCK STATUS CHECK (%ds after submission):' % delay
            print '  Block hash:    %064x' % block_hash
            print '  Height:        %s' % height
            print '  Confirmations: %s' % confirmations
            print '  ChainLock:     %s' % ('YES - LOCKED!' if chainlock else 'NO - not yet locked')
            
            if chainlock:
                print ''
                print '*** BLOCK CHAINLOCKED SUCCESSFULLY! ***'
                print '  Explorer: %s%064x' % (net.PARENT.BLOCK_EXPLORER_URL_PREFIX, block_hash)
                print ''
                defer.returnValue(True)
            
            if confirmations < 0:
                print ''
                print '*** WARNING: BLOCK MAY BE ORPHANED (confirmations=%d) ***' % confirmations
                print '  Another block may have been chainlocked at this height.'
                print ''
                # Check what block is at this height now
                try:
                    current_hash = yield coind.rpc_getblockhash(height)
                    if current_hash != '%064x' % block_hash:
                        print '  Current block at height %s: %s' % (height, current_hash)
                        current_block = yield coind.rpc_getblock(current_hash)
                        print '  Current block chainlock: %s' % current_block.get('chainlock', False)
                except Exception as e:
                    print '  Error checking current block: %s' % e
                defer.returnValue(False)
                
        except jsonrpc.Error_for_code(-5):
            # Block not found in local node - possibly orphaned
            if delay == 2:  # Only log once on first check
                print 'CHAINLOCK CHECK: Block %064x not found in local node' % block_hash
            defer.returnValue(False)
        except Exception as e:
            # Suppress SSL import errors (expected when OpenSSL not installed)
            if 'OpenSSL' in str(e) or 'SSL' in str(type(e).__name__):
                pass  # Silently skip SSL errors
            else:
                print 'CHAINLOCK CHECK: Error checking block: %s' % e
    
    print ''
    print '*** WARNING: Block not chainlocked after 60 seconds ***'
    print '  Block may be at risk of being orphaned if another chainlock wins.'
    print ''
    defer.returnValue(False)
