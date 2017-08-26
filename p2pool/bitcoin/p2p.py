'''
Implementation of Bitcoin's p2p protocol
'''

import random
import sys
import time

from twisted.internet import protocol

import p2pool
from . import data as bitcoin_data
from p2pool.util import deferral, p2protocol, pack, variable

class Protocol(p2protocol.Protocol):
    def __init__(self, net):
        p2protocol.Protocol.__init__(self, net.P2P_PREFIX, 1000000, ignore_trailing_payload=True)
    
    def connectionMade(self):
        self.send_version(
            version=70002,
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
        ('addr_to', bitcoin_data.address_type),
        ('addr_from', bitcoin_data.address_type),
        ('nonce', pack.IntType(64)),
        ('sub_version_num', pack.VarStrType()),
        ('start_height', pack.IntType(32)),
    ])
    def handle_version(self, version, services, time, addr_to, addr_from, nonce, sub_version_num, start_height):
        self.send_verack()
    
    message_verack = pack.ComposedType([])
    def handle_verack(self):
        self.get_block = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        self.get_block_header = deferral.ReplyMatcher(lambda hash: self.send_getheaders(version=1, have=[], last=hash))
        
        if hasattr(self.factory, 'resetDelay'):
            self.factory.resetDelay()
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(self)
        
        self.pinger = deferral.RobustLoopingCall(self.send_ping, nonce=1234)
        self.pinger.start(30)
    
    message_inv = pack.ComposedType([
        ('invs', pack.ListType(pack.ComposedType([
            ('type', pack.EnumType(pack.IntType(32), {1: 'tx', 2: 'block'})),
            ('hash', pack.IntType(256)),
        ]))),
    ])
    def handle_inv(self, invs):
        for inv in invs:
            if inv['type'] == 'tx':
                self.send_getdata(requests=[inv])
            elif inv['type'] == 'block':
                self.factory.new_block.happened(inv['hash'])
            else:
                print 'Unknown inv type', inv
    
    message_getdata = pack.ComposedType([
        ('requests', pack.ListType(pack.ComposedType([
            ('type', pack.EnumType(pack.IntType(32), {1: 'tx', 2: 'block'})),
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
    message_getaddr = pack.ComposedType([])
    
    message_addr = pack.ComposedType([
        ('addrs', pack.ListType(pack.ComposedType([
            ('timestamp', pack.IntType(32)),
            ('address', bitcoin_data.address_type),
        ]))),
    ])
    def handle_addr(self, addrs):
        for addr in addrs:
            pass
    
    message_tx = pack.ComposedType([
        ('tx', bitcoin_data.tx_type),
    ])
    def handle_tx(self, tx):
        self.factory.new_tx.happened(tx)
    
    message_block = pack.ComposedType([
        ('block', bitcoin_data.block_type),
    ])
    def handle_block(self, block):
        block_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(block['header']))
        self.get_block.got_response(block_hash, block)
        self.get_block_header.got_response(block_hash, block['header'])
    
    message_headers = pack.ComposedType([
        ('headers', pack.ListType(bitcoin_data.block_type)),
    ])
    def handle_headers(self, headers):
        for header in headers:
            header = header['header']
            self.get_block_header.got_response(bitcoin_data.hash256(bitcoin_data.block_header_type.pack(header)), header)
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

    message_reject = pack.ComposedType([
        ('message', pack.VarStrType()),
        ('ccode', pack.IntType(8)),
        ('reason', pack.VarStrType()),
        ('data', pack.IntType(256)),
    ])
    def handle_reject(self, message, ccode, reason, data):
        if p2pool.DEBUG:
            print >>sys.stderr, 'Received reject message (%s): %s' % (message, reason)
    
    def connectionLost(self, reason):
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(None)
        if hasattr(self, 'pinger'):
            self.pinger.stop()
        if p2pool.DEBUG:
            print >>sys.stderr, 'Bitcoin connection lost. Reason:', reason.getErrorMessage()

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
