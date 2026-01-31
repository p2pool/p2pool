'''
Implementation of Dash's p2p protocol
'''

import random
import sys
import time

from twisted.internet import protocol

import p2pool
from . import data as dash_data
from p2pool.util import deferral, p2protocol, pack, variable

class Protocol(p2protocol.Protocol):
    def __init__(self, net):
        p2protocol.Protocol.__init__(self, net.P2P_PREFIX, 3145728, ignore_trailing_payload=True)
        self.net = net

    def connectionMade(self):
        self.send_version(
            version=70238,
            services=1,
            time=int(time.time()),
            addr_to=dict(
                services=1,
                address=self.transport.getPeer().host,
                port=self.transport.getPeer().port,
            ),
            addr_from=dict(
                services=1,
                address=self.transport.getHost().host,
                port=self.transport.getHost().port,
            ),
            nonce=random.randrange(2**64),
            sub_version_num='/P2Pool:%s/' % (p2pool.__version__,),
            start_height=0,
        )

    message_version = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('services', pack.IntType(64)),
        ('time', pack.IntType(64)),
        ('addr_to', dash_data.address_type),
        ('addr_from', dash_data.address_type),
        ('nonce', pack.IntType(64)),
        ('sub_version_num', pack.VarStrType()),
        ('start_height', pack.IntType(32)),
    ])
    def handle_version(self, version, services, time, addr_to, addr_from, nonce, sub_version_num, start_height):
        self.send_verack()

    message_verack = pack.ComposedType([])
    def handle_verack(self):
        self.get_block = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        self.get_block_header = deferral.ReplyMatcher(lambda hash: self.send_getheaders(version=70238, have=[], last=hash))

        if hasattr(self.factory, 'resetDelay'):
            self.factory.resetDelay()
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(self)

        self.pinger = deferral.RobustLoopingCall(self.send_ping, nonce=1234)
        self.pinger.start(30)

    # https://github.com/dashpay/dash/blob/master/src/protocol.h#L441-L471
    message_inv = pack.ComposedType([
        ('invs', pack.ListType(pack.ComposedType([
            ('type', pack.EnumType(pack.IntType(32), {
                1: 'tx',
                2: 'block',
                3: 'filtered_block',
                4: 'txlock_request',
                5: 'txlock_vote',
                6: 'spork',
                7: 'masternode_winner',
                8: 'masternode_scanning_error',
                9: 'budget_vote',
                10: 'budget_proposal',
                11: 'budget_finalized',
                12: 'budget_finalized_vote',
                13: 'masternode_quorum',
                14: 'masternode_announce',
                15: 'masternode_ping',
                16: 'dstx',
                17: 'governance_object',
                18: 'governance_object_vote',
                19: 'masternode_verify',
                20: 'compact_block',
                21: 'quorum_final_commitment',
                22: 'quorum_dummy_commitment',
                23: 'quorum_contrib',
                24: 'quorum_complaint',
                25: 'quorum_justification',
                26: 'quorum_premature_commitment',
                27: 'quorum_debug_status',
                28: 'quorum_recovered_sig',
                29: 'clsig',
                30: 'islock',
                31: 'isdlock',
                32: 'dsq',
                33: 'platform_ban'
            })),
            ('hash', pack.IntType(256)),
        ]))),
    ])
    def handle_inv(self, invs):
        for inv in invs:
            if inv['type'] == 'block':
                self.factory.new_block.happened(inv['hash'])
            elif inv['type'] == 'tx':
                self.send_getdata(requests=[inv])
            else:
                if p2pool.DEBUG:
                    print 'Unneeded inv type', inv

    message_getdata = pack.ComposedType([
        ('requests', pack.ListType(pack.ComposedType([
            ('type', pack.EnumType(pack.IntType(32), {
                1: 'tx',
                2: 'block',
                3: 'filtered_block',
                4: 'txlock_request',
                5: 'txlock_vote',
                6: 'spork',
                7: 'masternode_winner',
                8: 'masternode_scanning_error',
                9: 'budget_vote',
                10: 'budget_proposal',
                11: 'budget_finalized',
                12: 'budget_finalized_vote',
                13: 'masternode_quorum',
                14: 'masternode_announce',
                15: 'masternode_ping',
                16: 'dstx',
                17: 'governance_object',
                18: 'governance_object_vote',
                19: 'masternode_verify',
                20: 'compact_block',
                21: 'quorum_final_commitment',
                22: 'quorum_dummy_commitment',
                23: 'quorum_contrib',
                24: 'quorum_complaint',
                25: 'quorum_justification',
                26: 'quorum_premature_commitment',
                27: 'quorum_debug_status',
                28: 'quorum_recovered_sig',
                29: 'clsig',
                30: 'islock',
                31: 'isdlock',
                32: 'dsq',
                33: 'platform_ban'
            })),
            ('hash', pack.IntType(256)),
        ]))),
    ])
    message_getblocks = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('have', pack.ListType(pack.IntType(256))),
        ('last', pack.PossiblyNoneType(0, pack.IntType(256))),
    ])
    message_getheaders = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('have', pack.ListType(pack.IntType(256))),
        ('last', pack.PossiblyNoneType(0, pack.IntType(256))),
    ])
    def handle_getheaders(self, version, have, last):
        pass
    message_sendheaders = pack.ComposedType([])
    def handle_sendheaders(self):
        pass
    message_sendcmpct = pack.ComposedType([
        ('announce', pack.BoolType()),
        ('version', pack.IntType(64)),
    ])
    def handle_sendcmpct(self, announce, version):
        pass

    message_getaddr = pack.ComposedType([])

    message_addr = pack.ComposedType([
        ('addrs', pack.ListType(pack.ComposedType([
            ('timestamp', pack.IntType(32)),
            ('address', dash_data.address_type),
        ]))),
    ])
    def handle_addr(self, addrs):
        for addr in addrs:
            pass

    message_tx = pack.ComposedType([
        ('tx', dash_data.tx_type),
    ])
    def handle_tx(self, tx):
        self.factory.new_tx.happened(tx)

    message_block = pack.ComposedType([
        ('block', dash_data.block_type),
    ])
    def handle_block(self, block):
        block_hash = self.net.BLOCKHASH_FUNC(dash_data.block_header_type.pack(block['header']))
        self.get_block.got_response(block_hash, block)
        self.get_block_header.got_response(block_hash, block['header'])

    message_block_old = pack.ComposedType([
        ('block', dash_data.block_type_old),
    ])
    def handle_block_old(self, block):
        block_hash = self.net.BLOCKHASH_FUNC(dash_data.block_header_type.pack(block['header']))
        self.get_block.got_response(block_hash, block)
        self.get_block_header.got_response(block_hash, block['header'])

    message_headers = pack.ComposedType([
        ('headers', pack.ListType(dash_data.block_type_old)),
    ])
    def handle_headers(self, headers):
        for header in headers:
            header = header['header']
            self.get_block_header.got_response(self.net.BLOCKHASH_FUNC(dash_data.block_header_type.pack(header)), header)
        self.factory.new_headers.happened([header['header'] for header in headers])

    message_ping = pack.ComposedType([
        ('nonce', pack.IntType(64)),
    ])
    def handle_ping(self, nonce):
        self.send_pong(nonce=nonce)

    message_pong = pack.ComposedType([
        ('nonce', pack.IntType(64)),
    ])
    def handle_pong(self, nonce):
        pass

    message_alert = pack.ComposedType([
        ('message', pack.VarStrType()),
        ('signature', pack.VarStrType()),
    ])
    def handle_alert(self, message, signature):
        pass # print 'ALERT:', (message, signature)

    message_dsq = pack.ComposedType([
        ('denom', pack.IntType(32)),
        ('masternode_outpoint', pack.PossiblyNoneType(dict(hash=0, index=0), pack.ComposedType([
            ('hash', pack.IntType(256)),
            ('index', pack.IntType(32)),
        ]))),
        ('time', pack.IntType(64)),
        ('signature', pack.PossiblyNoneType(b'', pack.VarStrType())),
    ])
    def handle_dsq(self, denom, masternode_outpoint, time, signature):
        pass # print 'dsq:', (denom, masternode_outpoint, time, signature)

    def connectionLost(self, reason):
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(None)
        if hasattr(self, 'pinger'):
            self.pinger.stop()
        if p2pool.DEBUG:
            print >>sys.stderr, 'Dashd connection lost. Reason:', reason.getErrorMessage()

class ClientFactory(protocol.ReconnectingClientFactory):
    protocol = Protocol

    maxDelay = 1

    def __init__(self, net):
        self.net = net
        self.conn = variable.Variable(None)

        self.new_block = variable.Event()
        self.new_tx = variable.Event()
        self.new_headers = variable.Event()

    def buildProtocol(self, addr):
        p = self.protocol(self.net)
        p.factory = self
        return p

    def gotConnection(self, conn):
        self.conn.set(conn)

    def getProtocol(self):
        return self.conn.get_not_none()
