from __future__ import division

import base64
import gc
import json
import os
import random
import sys
import time
import signal
import traceback
import urlparse

if '--iocp' in sys.argv:
    from twisted.internet import iocpreactor
    iocpreactor.install()
from twisted.internet import defer, reactor, protocol, tcp
from twisted.web import server
from twisted.python import log
from nattraverso import portmapper, ipdiscover

import bitcoin.p2p as bitcoin_p2p, bitcoin.data as bitcoin_data
from bitcoin import stratum, worker_interface, helper
from util import fixargparse, jsonrpc, variable, deferral, math, logging, switchprotocol
from . import networks, web, work
import p2pool, p2pool.data as p2pool_data, p2pool.node as p2pool_node

class keypool():
    keys = []
    keyweights = []
    stamp = time.time()
    payouttotal = 0.0

    def addkey(self, n):
        self.keys.append(n)
        self.keyweights.append(random.uniform(0,100.0))
    def delkey(self, n):
        try:
            i=self.keys.index(n)
            self.keys.pop(i)
            self.keyweights.pop(i)
        except:
            pass

    def weighted(self):
        choice=random.uniform(0,sum(self.keyweights))
        tot = 0.0
        ind = 0
        for i in (self.keyweights):
            tot += i
            if tot >= choice:
                return ind
            ind += 1
        return ind

    def popleft(self):
        if (len(self.keys) > 0):
            dummyval=self.keys.pop(0)
        if (len(self.keyweights) > 0):
            dummyval=self.keyweights.pop(0)

    def updatestamp(self, n):
        self.stamp = n

    def paytotal(self):
        self.payouttotal = 0.0
        for i in range(len(pubkeys.keys)):
            self.payouttotal += node.get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(pubkeys.keys[i]), 0)*1e-8
        return self.payouttotal

    def getpaytotal(self):
        return self.payouttotal

@defer.inlineCallbacks
def main(args, net, datadir_path, merged_urls, worker_endpoint):
    try:
        print 'p2pool (version %s)' % (p2pool.__version__,)
        print
        
        @defer.inlineCallbacks
        def connect_p2p():
            # connect to bitcoind over bitcoin-p2p
            print '''Testing bitcoind P2P connection to '%s:%s'...''' % (args.bitcoind_address, args.bitcoind_p2p_port)
            factory = bitcoin_p2p.ClientFactory(net.PARENT)
            reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
            def long():
                print '''    ...taking a while. Common reasons for this include all of bitcoind's connection slots being used...'''
            long_dc = reactor.callLater(5, long)
            yield factory.getProtocol() # waits until handshake is successful
            if not long_dc.called: long_dc.cancel()
            print '    ...success!'
            print
            defer.returnValue(factory)
        
        if args.testnet: # establish p2p connection first if testnet so bitcoind can work without connections
            factory = yield connect_p2p()
        
        # connect to bitcoind over JSON-RPC and do initial getmemorypool
        url = '%s://%s:%i/' % ('https' if args.bitcoind_rpc_ssl else 'http', args.bitcoind_address, args.bitcoind_rpc_port)
        print '''Testing bitcoind RPC connection to '%s' with username '%s'...''' % (url, args.bitcoind_rpc_username)
        bitcoind = jsonrpc.HTTPProxy(url, dict(Authorization='Basic ' + base64.b64encode(args.bitcoind_rpc_username + ':' + args.bitcoind_rpc_password)), timeout=30)
        yield helper.check(bitcoind, net)
        temp_work = yield helper.getwork(bitcoind)
        
        bitcoind_getinfo_var = variable.Variable(None)
        @defer.inlineCallbacks
        def poll_warnings():
            bitcoind_getinfo_var.set((yield deferral.retry('Error while calling getinfo:')(bitcoind.rpc_getinfo)()))
        yield poll_warnings()
        deferral.RobustLoopingCall(poll_warnings).start(20*60)
        
        print '    ...success!'
        print '    Current block hash: %x' % (temp_work['previous_block'],)
        print '    Current block height: %i' % (temp_work['height'] - 1,)
        print
        
        if not args.testnet:
            factory = yield connect_p2p()
        
        print 'Determining payout address...'
        pubkeys = keypool()
        if args.pubkey_hash is None and args.address != 'dynamic':
            address_path = os.path.join(datadir_path, 'cached_payout_address')
            
            if os.path.exists(address_path):
                with open(address_path, 'rb') as f:
                    address = f.read().strip('\r\n')
                print '    Loaded cached address: %s...' % (address,)
            else:
                address = None
            
            if address is not None:
                res = yield deferral.retry('Error validating cached address:', 5)(lambda: bitcoind.rpc_validateaddress(address))()
                if not res['isvalid'] or not res['ismine']:
                    print '    Cached address is either invalid or not controlled by local bitcoind!'
                    address = None
            
            if address is None:
                print '    Getting payout address from bitcoind...'
                address = yield deferral.retry('Error getting payout address from bitcoind:', 5)(lambda: bitcoind.rpc_getaccountaddress('p2pool'))()
            
            with open(address_path, 'wb') as f:
                f.write(address)
            
            my_pubkey_hash = bitcoin_data.address_to_pubkey_hash(address, net.PARENT)
            print '    ...success! Payout address:', bitcoin_data.pubkey_hash_to_address(my_pubkey_hash, net.PARENT)
            print
            pubkeys.addkey(my_pubkey_hash)
        elif args.address != 'dynamic':
            my_pubkey_hash = args.pubkey_hash
            print '    ...success! Payout address:', bitcoin_data.pubkey_hash_to_address(my_pubkey_hash, net.PARENT)
            print
            pubkeys.addkey(my_pubkey_hash)
        else:
            print '    Entering dynamic address mode.'

            if args.numaddresses < 2:
                print ' ERROR: Can not use fewer than 2 addresses in dynamic mode. Resetting to 2.'
                args.numaddresses = 2
            for i in range(args.numaddresses):
                address = yield deferral.retry('Error getting a dynamic address from bitcoind:', 5)(lambda: bitcoind.rpc_getnewaddress('p2pool'))()
                new_pubkey = bitcoin_data.address_to_pubkey_hash(address, net.PARENT)
                pubkeys.addkey(new_pubkey)

            pubkeys.updatestamp(time.time())

            my_pubkey_hash = pubkeys.keys[0]

            for i in range(len(pubkeys.keys)):
                print '    ...payout %d: %s' % (i, bitcoin_data.pubkey_hash_to_address(pubkeys.keys[i], net.PARENT),)
        
        print "Loading shares..."
        shares = {}
        known_verified = set()
        def share_cb(share):
            share.time_seen = 0 # XXX
            shares[share.hash] = share
            if len(shares) % 1000 == 0 and shares:
                print "    %i" % (len(shares),)
        ss = p2pool_data.ShareStore(os.path.join(datadir_path, 'shares.'), net, share_cb, known_verified.add)
        print "    ...done loading %i shares (%i verified)!" % (len(shares), len(known_verified))
        print
        
        
        print 'Initializing work...'
        
        node = p2pool_node.Node(factory, bitcoind, shares.values(), known_verified, net)
        yield node.start()
        
        for share_hash in shares:
            if share_hash not in node.tracker.items:
                ss.forget_share(share_hash)
        for share_hash in known_verified:
            if share_hash not in node.tracker.verified.items:
                ss.forget_verified_share(share_hash)
        node.tracker.removed.watch(lambda share: ss.forget_share(share.hash))
        node.tracker.verified.removed.watch(lambda share: ss.forget_verified_share(share.hash))
        
        def save_shares():
            for share in node.tracker.get_chain(node.best_share_var.value, min(node.tracker.get_height(node.best_share_var.value), 2*net.CHAIN_LENGTH)):
                ss.add_share(share)
                if share.hash in node.tracker.verified.items:
                    ss.add_verified_hash(share.hash)
        deferral.RobustLoopingCall(save_shares).start(60)
        
        print '    ...success!'
        print
        
        
        print 'Joining p2pool network using port %i...' % (args.p2pool_port,)
        
        @defer.inlineCallbacks
        def parse(host):
            port = net.P2P_PORT
            if ':' in host:
                host, port_str = host.split(':')
                port = int(port_str)
            defer.returnValue(((yield reactor.resolve(host)), port))
        
        addrs = {}
        if os.path.exists(os.path.join(datadir_path, 'addrs')):
            try:
                with open(os.path.join(datadir_path, 'addrs'), 'rb') as f:
                    addrs.update(dict((tuple(k), v) for k, v in json.loads(f.read())))
            except:
                print >>sys.stderr, 'error parsing addrs'
        for addr_df in map(parse, net.BOOTSTRAP_ADDRS):
            try:
                addr = yield addr_df
                if addr not in addrs:
                    addrs[addr] = (0, time.time(), time.time())
            except:
                log.err()
        
        connect_addrs = set()
        for addr_df in map(parse, args.p2pool_nodes):
            try:
                connect_addrs.add((yield addr_df))
            except:
                log.err()
        
        node.p2p_node = p2pool_node.P2PNode(node,
            port=args.p2pool_port,
            max_incoming_conns=args.p2pool_conns,
            addr_store=addrs,
            connect_addrs=connect_addrs,
            desired_outgoing_conns=args.p2pool_outgoing_conns,
            advertise_ip=args.advertise_ip,
            external_ip=args.p2pool_external_ip,
        )
        node.p2p_node.start()
        
        def save_addrs():
            with open(os.path.join(datadir_path, 'addrs'), 'wb') as f:
                f.write(json.dumps(node.p2p_node.addr_store.items()))
        deferral.RobustLoopingCall(save_addrs).start(60)
        
        print '    ...success!'
        print
        
        if args.upnp:
            @defer.inlineCallbacks
            def upnp_thread():
                while True:
                    try:
                        is_lan, lan_ip = yield ipdiscover.get_local_ip()
                        if is_lan:
                            pm = yield portmapper.get_port_mapper()
                            yield pm._upnp.add_port_mapping(lan_ip, args.p2pool_port, args.p2pool_port, 'p2pool', 'TCP')
                    except defer.TimeoutError:
                        pass
                    except:
                        if p2pool.DEBUG:
                            log.err(None, 'UPnP error:')
                    yield deferral.sleep(random.expovariate(1/120))
            upnp_thread()
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on %r port %i...' % (worker_endpoint[0], worker_endpoint[1])
        
        wb = work.WorkerBridge(node, my_pubkey_hash, args.donation_percentage, merged_urls, args.worker_fee, args, pubkeys, bitcoind)
        web_root = web.get_web_root(wb, datadir_path, bitcoind_getinfo_var)
        caching_wb = worker_interface.CachingWorkerBridge(wb)
        worker_interface.WorkerInterface(caching_wb).attach_to(web_root, get_handler=lambda request: request.redirect('/static/'))
        web_serverfactory = server.Site(web_root)
        
        serverfactory = switchprotocol.FirstByteSwitchFactory({'{': stratum.StratumServerFactory(caching_wb)}, web_serverfactory)
        deferral.retry('Error binding to worker port:', traceback=False)(reactor.listenTCP)(worker_endpoint[1], serverfactory, interface=worker_endpoint[0])
        
        with open(os.path.join(os.path.join(datadir_path, 'ready_flag')), 'wb') as f:
            pass
        
        print '    ...success!'
        print
        
        
        # done!
        print 'Started successfully!'
        print 'Go to http://127.0.0.1:%i/ to view graphs and statistics!' % (worker_endpoint[1],)
        if args.donation_percentage > 1.1:
            print '''Donating %.1f%% of work towards P2Pool's development. Thanks for the tip!''' % (args.donation_percentage,)
        elif args.donation_percentage < .9:
            print '''Donating %.1f%% of work towards P2Pool's development. Please donate to encourage further development of P2Pool!''' % (args.donation_percentage,)
        else:
            print '''Donating %.1f%% of work towards P2Pool's development. Thank you!''' % (args.donation_percentage,)
            print 'You can increase this amount with --give-author argument! (or decrease it, if you must)'
        print
        
        
        if hasattr(signal, 'SIGALRM'):
            signal.signal(signal.SIGALRM, lambda signum, frame: reactor.callFromThread(
                sys.stderr.write, 'Watchdog timer went off at:\n' + ''.join(traceback.format_stack())
            ))
            signal.siginterrupt(signal.SIGALRM, False)
            deferral.RobustLoopingCall(signal.alarm, 30).start(1)
        
        if args.irc_announce:
            from twisted.words.protocols import irc
            class IRCClient(irc.IRCClient):
                nickname = 'p2pool%02i' % (random.randrange(100),)
                channel = net.ANNOUNCE_CHANNEL
                def lineReceived(self, line):
                    if p2pool.DEBUG:
                        print repr(line)
                    irc.IRCClient.lineReceived(self, line)
                def signedOn(self):
                    self.in_channel = False
                    irc.IRCClient.signedOn(self)
                    self.factory.resetDelay()
                    self.join(self.channel)
                    @defer.inlineCallbacks
                    def new_share(share):
                        if not self.in_channel:
                            return
                        if share.pow_hash <= share.header['bits'].target and abs(share.timestamp - time.time()) < 10*60:
                            yield deferral.sleep(random.expovariate(1/60))
                            message = '\x02%s BLOCK FOUND by %s! %s%064x' % (net.NAME.upper(), bitcoin_data.script2_to_address(share.new_script, net.PARENT), net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header_hash)
                            if all('%x' % (share.header_hash,) not in old_message for old_message in self.recent_messages):
                                self.say(self.channel, message)
                                self._remember_message(message)
                    self.watch_id = node.tracker.verified.added.watch(new_share)
                    self.recent_messages = []
                def joined(self, channel):
                    self.in_channel = True
                def left(self, channel):
                    self.in_channel = False
                def _remember_message(self, message):
                    self.recent_messages.append(message)
                    while len(self.recent_messages) > 100:
                        self.recent_messages.pop(0)
                def privmsg(self, user, channel, message):
                    if channel == self.channel:
                        self._remember_message(message)
                def connectionLost(self, reason):
                    node.tracker.verified.added.unwatch(self.watch_id)
                    print 'IRC connection lost:', reason.getErrorMessage()
            class IRCClientFactory(protocol.ReconnectingClientFactory):
                protocol = IRCClient
            reactor.connectTCP("irc.freenode.net", 6667, IRCClientFactory(), bindAddress=(worker_endpoint[0], 0))
        
        @defer.inlineCallbacks
        def status_thread():
            last_str = None
            last_time = 0
            while True:
                yield deferral.sleep(3)
                try:
                    height = node.tracker.get_height(node.best_share_var.value)
                    this_str = 'P2Pool: %i shares in chain (%i verified/%i total) Peers: %i (%i incoming)' % (
                        height,
                        len(node.tracker.verified.items),
                        len(node.tracker.items),
                        len(node.p2p_node.peers),
                        sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                    ) + (' FDs: %i R/%i W' % (len(reactor.getReaders()), len(reactor.getWriters())) if p2pool.DEBUG else '')
                    
                    datums, dt = wb.local_rate_monitor.get_datums_in_last()
                    my_att_s = sum(datum['work']/dt for datum in datums)
                    my_shares_per_s = sum(datum['work']/dt/bitcoin_data.target_to_average_attempts(datum['share_target']) for datum in datums)
                    this_str += '\n Local: %sH/s in last %s Local dead on arrival: %s Expected time to share: %s' % (
                        math.format(int(my_att_s)),
                        math.format_dt(dt),
                        math.format_binomial_conf(sum(1 for datum in datums if datum['dead']), len(datums), 0.95),
                        math.format_dt(1/my_shares_per_s) if my_shares_per_s else '???',
                    )
                    
                    if height > 2:
                        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()
                        stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, min(60*60//net.SHARE_PERIOD, height))
                        real_att_s = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, min(height - 1, 60*60//net.SHARE_PERIOD)) / (1 - stale_prop)
                        
                        paystr = ''
                        paytot = 0.0
                        for i in range(len(pubkeys.keys)):
                            curtot = node.get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(pubkeys.keys[i]), 0)
                            paytot += curtot*1e-8
                            paystr += "(%.4f)" % (curtot*1e-8,)
                        paystr += "=%.4f" % (paytot,)
                        this_str += '\n Shares: %i (%i orphan, %i dead) Stale rate: %s Efficiency: %s Current payout: %s %s' % (
                            shares, stale_orphan_shares, stale_doa_shares,
                            math.format_binomial_conf(stale_orphan_shares + stale_doa_shares, shares, 0.95),
                            math.format_binomial_conf(stale_orphan_shares + stale_doa_shares, shares, 0.95, lambda x: (1 - x)/(1 - stale_prop)),
                            paystr, net.PARENT.SYMBOL,
                        )
                        this_str += '\n Pool: %sH/s Stale rate: %.1f%% Expected time to block: %s' % (
                            math.format(int(real_att_s)),
                            100*stale_prop,
                            math.format_dt(2**256 / node.bitcoind_work.value['bits'].target / real_att_s),
                        )
                        
                        for warning in p2pool_data.get_warnings(node.tracker, node.best_share_var.value, net, bitcoind_getinfo_var.value, node.bitcoind_work.value):
                            print >>sys.stderr, '#'*40
                            print >>sys.stderr, '>>> Warning: ' + warning
                            print >>sys.stderr, '#'*40
                        
                        if gc.garbage:
                            print '%i pieces of uncollectable cyclic garbage! Types: %r' % (len(gc.garbage), map(type, gc.garbage))
                    
                    if this_str != last_str or time.time() > last_time + 15:
                        print this_str
                        last_str = this_str
                        last_time = time.time()
                except:
                    log.err()
        status_thread()
    except:
        reactor.stop()
        log.err(None, 'Fatal error:')

def run():
    if not hasattr(tcp.Client, 'abortConnection'):
        print "Twisted doesn't have abortConnection! Upgrade to a newer version of Twisted to avoid memory leaks!"
        print 'Pausing for 3 seconds...'
        time.sleep(3)
    
    realnets = dict((name, net) for name, net in networks.nets.iteritems() if '_testnet' not in name)
    
    parser = fixargparse.FixedArgumentParser(description='p2pool (version %s)' % (p2pool.__version__,), fromfile_prefix_chars='@')
    parser.add_argument('--version', action='version', version=p2pool.__version__)
    parser.add_argument('--net',
        help='use specified network (default: bitcoin)',
        action='store', choices=sorted(realnets), default='bitcoin', dest='net_name')
    parser.add_argument('--testnet',
        help='''use the network's testnet''',
        action='store_const', const=True, default=False, dest='testnet')
    parser.add_argument('--debug',
        help='enable debugging mode',
        action='store_const', const=True, default=False, dest='debug')
    parser.add_argument('-a', '--address',
        help='generate payouts to this address (default: <address requested from bitcoind>), or (dynamic)',
        type=str, action='store', default=None, dest='address')
    parser.add_argument('-i', '--numaddresses',
        help='number of bitcoin auto-generated addresses to maintain for getwork dynamic address allocation',
        type=int, action='store', default=2, dest='numaddresses')
    parser.add_argument('-t', '--timeaddresses',
        help='seconds between acquisition of new address and removal of single old (default: 2 days or 172800s)',
        type=int, action='store', default=172800, dest='timeaddresses')
    parser.add_argument('--datadir',
        help='store data in this directory (default: <directory run_p2pool.py is in>/data)',
        type=str, action='store', default=None, dest='datadir')
    parser.add_argument('--logfile',
        help='''log to this file (default: data/<NET>/log)''',
        type=str, action='store', default=None, dest='logfile')
    parser.add_argument('--merged',
        help='call getauxblock on this url to get work for merged mining (example: http://ncuser:ncpass@127.0.0.1:10332/)',
        type=str, action='append', default=[], dest='merged_urls')
    parser.add_argument('--give-author', metavar='DONATION_PERCENTAGE',
        help='donate this percentage of work towards the development of p2pool (default: 1.0)',
        type=float, action='store', default=1.0, dest='donation_percentage')
    parser.add_argument('--iocp',
        help='use Windows IOCP API in order to avoid errors due to large number of sockets being open',
        action='store_true', default=False, dest='iocp')
    parser.add_argument('--irc-announce',
        help='announce any blocks found on irc://irc.freenode.net/#p2pool',
        action='store_true', default=False, dest='irc_announce')
    parser.add_argument('--no-bugreport',
        help='disable submitting caught exceptions to the author',
        action='store_true', default=False, dest='no_bugreport')
    
    p2pool_group = parser.add_argument_group('p2pool interface')
    p2pool_group.add_argument('--p2pool-port', metavar='PORT',
        help='use port PORT to listen for connections (forward this port from your router!) (default: %s)' % ', '.join('%s:%i' % (name, net.P2P_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='p2pool_port')
    p2pool_group.add_argument('-n', '--p2pool-node', metavar='ADDR[:PORT]',
        help='connect to existing p2pool node at ADDR listening on port PORT (defaults to default p2pool P2P port) in addition to builtin addresses',
        type=str, action='append', default=[], dest='p2pool_nodes')
    parser.add_argument('--disable-upnp',
        help='''don't attempt to use UPnP to forward p2pool's P2P port from the Internet to this computer''',
        action='store_false', default=True, dest='upnp')
    p2pool_group.add_argument('--max-conns', metavar='CONNS',
        help='maximum incoming connections (default: 40)',
        type=int, action='store', default=40, dest='p2pool_conns')
    p2pool_group.add_argument('--outgoing-conns', metavar='CONNS',
        help='outgoing connections (default: 6)',
        type=int, action='store', default=6, dest='p2pool_outgoing_conns')
    p2pool_group.add_argument('--external-ip', metavar='ADDR[:PORT]',
        help='specify your own public IP address instead of asking peers to discover it, useful for running dual WAN or asymmetric routing',
        type=str, action='store', default=None, dest='p2pool_external_ip')
    parser.add_argument('--disable-advertise',
        help='''don't advertise local IP address as being available for incoming connections. useful for running a dark node, along with multiple -n ADDR's and --outgoing-conns 0''',
        action='store_false', default=True, dest='advertise_ip')
    
    worker_group = parser.add_argument_group('worker interface')
    worker_group.add_argument('-w', '--worker-port', metavar='PORT or ADDR:PORT',
        help='listen on PORT on interface with ADDR for RPC connections from miners (default: all interfaces, %s)' % ', '.join('%s:%i' % (name, net.WORKER_PORT) for name, net in sorted(realnets.items())),
        type=str, action='store', default=None, dest='worker_endpoint')
    worker_group.add_argument('-f', '--fee', metavar='FEE_PERCENTAGE',
        help='''charge workers mining to their own bitcoin address (by setting their miner's username to a bitcoin address) this percentage fee to mine on your p2pool instance. Amount displayed at http://127.0.0.1:WORKER_PORT/fee (default: 0)''',
        type=float, action='store', default=0, dest='worker_fee')
    worker_group.add_argument('-d', '--difficulty', metavar='DIFFICULTY',
        help='''set difficulty policy: D - default, A - adaptive, F - force adaptive (ignore miner's request)''',
        type=str, action='store', default='D', dest='diff_policy')
    
    bitcoind_group = parser.add_argument_group('bitcoind interface')
    bitcoind_group.add_argument('--bitcoind-config-path', metavar='BITCOIND_CONFIG_PATH',
        help='custom configuration file path (when bitcoind -conf option used)',
        type=str, action='store', default=None, dest='bitcoind_config_path')
    bitcoind_group.add_argument('--bitcoind-address', metavar='BITCOIND_ADDRESS',
        help='connect to this address (default: 127.0.0.1)',
        type=str, action='store', default='127.0.0.1', dest='bitcoind_address')
    bitcoind_group.add_argument('--bitcoind-rpc-port', metavar='BITCOIND_RPC_PORT',
        help='''connect to JSON-RPC interface at this port (default: %s <read from bitcoin.conf if password not provided>)''' % ', '.join('%s:%i' % (name, net.PARENT.RPC_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='bitcoind_rpc_port')
    bitcoind_group.add_argument('--bitcoind-rpc-ssl',
        help='connect to JSON-RPC interface using SSL',
        action='store_true', default=False, dest='bitcoind_rpc_ssl')
    bitcoind_group.add_argument('--bitcoind-p2p-port', metavar='BITCOIND_P2P_PORT',
        help='''connect to P2P interface at this port (default: %s <read from bitcoin.conf if password not provided>)''' % ', '.join('%s:%i' % (name, net.PARENT.P2P_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='bitcoind_p2p_port')
    bitcoind_group.add_argument(metavar='BITCOIND_RPCUSERPASS',
        help='bitcoind RPC interface username, then password, space-separated (only one being provided will cause the username to default to being empty, and none will cause P2Pool to read them from bitcoin.conf)',
        type=str, action='store', default=[], nargs='*', dest='bitcoind_rpc_userpass')
    
    args = parser.parse_args()
    
    if args.debug:
        p2pool.DEBUG = True
        defer.setDebugging(True)
    else:
        p2pool.DEBUG = False
    
    net_name = args.net_name + ('_testnet' if args.testnet else '')
    net = networks.nets[net_name]
    
    datadir_path = os.path.join((os.path.join(os.path.dirname(sys.argv[0]), 'data') if args.datadir is None else args.datadir), net_name)
    if not os.path.exists(datadir_path):
        os.makedirs(datadir_path)
    
    if len(args.bitcoind_rpc_userpass) > 2:
        parser.error('a maximum of two arguments are allowed')
    args.bitcoind_rpc_username, args.bitcoind_rpc_password = ([None, None] + args.bitcoind_rpc_userpass)[-2:]
    
    if args.bitcoind_rpc_password is None:
        conf_path = args.bitcoind_config_path or net.PARENT.CONF_FILE_FUNC()
        if not os.path.exists(conf_path):
            parser.error('''Bitcoin configuration file not found. Manually enter your RPC password.\r\n'''
                '''If you actually haven't created a configuration file, you should create one at %s with the text:\r\n'''
                '''\r\n'''
                '''server=1\r\n'''
                '''rpcpassword=%x\r\n'''
                '''\r\n'''
                '''Keep that password secret! After creating the file, restart Bitcoin.''' % (conf_path, random.randrange(2**128)))
        conf = open(conf_path, 'rb').read()
        contents = {}
        for line in conf.splitlines(True):
            if '#' in line:
                line = line[:line.index('#')]
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            contents[k.strip()] = v.strip()
        for conf_name, var_name, var_type in [
            ('rpcuser', 'bitcoind_rpc_username', str),
            ('rpcpassword', 'bitcoind_rpc_password', str),
            ('rpcport', 'bitcoind_rpc_port', int),
            ('port', 'bitcoind_p2p_port', int),
        ]:
            if getattr(args, var_name) is None and conf_name in contents:
                setattr(args, var_name, var_type(contents[conf_name]))
        if 'rpcssl' in contents and contents['rpcssl'] != '0':
            args.bitcoind_rpc_ssl = True
        if args.bitcoind_rpc_password is None:
            parser.error('''Bitcoin configuration file didn't contain an rpcpassword= line! Add one!''')
    
    if args.bitcoind_rpc_username is None:
        args.bitcoind_rpc_username = ''
    
    if args.bitcoind_rpc_port is None:
        args.bitcoind_rpc_port = net.PARENT.RPC_PORT
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = net.PARENT.P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = net.P2P_PORT
    
    if args.p2pool_outgoing_conns > 10:
        parser.error('''--outgoing-conns can't be more than 10''')
    
    if args.worker_endpoint is None:
        worker_endpoint = '', net.WORKER_PORT
    elif ':' not in args.worker_endpoint:
        worker_endpoint = '', int(args.worker_endpoint)
    else:
        addr, port = args.worker_endpoint.rsplit(':', 1)
        worker_endpoint = addr, int(port)
    
    if args.address is not None and args.address != 'dynamic':
        try:
            args.pubkey_hash = bitcoin_data.address_to_pubkey_hash(args.address, net.PARENT)
        except Exception, e:
            parser.error('error parsing address: ' + repr(e))
    else:
        args.pubkey_hash = None
    
    def separate_url(url):
        s = urlparse.urlsplit(url)
        if '@' not in s.netloc:
            parser.error('merged url netloc must contain an "@"')
        userpass, new_netloc = s.netloc.rsplit('@', 1)
        return urlparse.urlunsplit(s._replace(netloc=new_netloc)), userpass
    merged_urls = map(separate_url, args.merged_urls)
    
    if args.logfile is None:
        args.logfile = os.path.join(datadir_path, 'log')
    
    logfile = logging.LogFile(args.logfile)
    pipe = logging.TimestampingPipe(logging.TeePipe([logging.EncodeReplacerPipe(sys.stderr), logfile]))
    sys.stdout = logging.AbortPipe(pipe)
    sys.stderr = log.DefaultObserver.stderr = logging.AbortPipe(logging.PrefixPipe(pipe, '> '))
    if hasattr(signal, "SIGUSR1"):
        def sigusr1(signum, frame):
            print 'Caught SIGUSR1, closing %r...' % (args.logfile,)
            logfile.reopen()
            print '...and reopened %r after catching SIGUSR1.' % (args.logfile,)
        signal.signal(signal.SIGUSR1, sigusr1)
    deferral.RobustLoopingCall(logfile.reopen).start(5)
    
    class ErrorReporter(object):
        def __init__(self):
            self.last_sent = None
        
        def emit(self, eventDict):
            if not eventDict["isError"]:
                return
            
            if self.last_sent is not None and time.time() < self.last_sent + 5:
                return
            self.last_sent = time.time()
            
            if 'failure' in eventDict:
                text = ((eventDict.get('why') or 'Unhandled Error')
                    + '\n' + eventDict['failure'].getTraceback())
            else:
                text = " ".join([str(m) for m in eventDict["message"]]) + "\n"
            
            from twisted.web import client
            client.getPage(
                url='http://u.forre.st/p2pool_error.cgi',
                method='POST',
                postdata=p2pool.__version__ + ' ' + net.NAME + '\n' + text,
                timeout=15,
            ).addBoth(lambda x: None)
    if not args.no_bugreport:
        log.addObserver(ErrorReporter().emit)
    
    reactor.callWhenRunning(main, args, net, datadir_path, merged_urls, worker_endpoint)
    reactor.run()
