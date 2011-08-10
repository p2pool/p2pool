"""
Generic methods to retreive the IP address of the local machine.

TODO: Example

@author: Raphael Slinckx
@copyright: Copyright 2005
@license: LGPL
@contact: U{raphael@slinckx.net<mailto:raphael@slinckx.net>}
@version: 0.1.0
"""

__revision__ = "$id"

import random, socket, logging, itertools

from twisted.internet import defer, reactor

from twisted.internet.protocol import DatagramProtocol
from twisted.internet.error import CannotListenError

from nattraverso.utils import is_rfc1918_ip, is_bogus_ip

@defer.inlineCallbacks
def get_local_ip():
    """
    Returns a deferred which will be called with a
    2-uple (lan_flag, ip_address) :
        - lan_flag:
            - True if it's a local network (RFC1918)
            - False if it's a WAN address
        
        - ip_address is the actual ip address
    
    @return: A deferred called with the above defined tuple
    @rtype: L{twisted.internet.defer.Deferred}
    """
    # first we try a connected udp socket, then via multicast
    logging.debug("Resolving dns to get udp ip")
    try:
        ipaddr = yield reactor.resolve('A.ROOT-SERVERS.NET')
    except:
        pass
    else:
        udpprot = DatagramProtocol()
        port = reactor.listenUDP(0, udpprot)
        udpprot.transport.connect(ipaddr, 7)
        localip = udpprot.transport.getHost().host
        port.stopListening()
        
        if is_bogus_ip(localip):
            raise RuntimeError, "Invalid IP address returned"
        else:
            defer.returnValue((is_rfc1918_ip(localip), localip))
    
    logging.debug("Multicast ping to retrieve local IP")
    ipaddr = yield _discover_multicast()
    defer.returnValue((is_rfc1918_ip(ipaddr), ipaddr))

@defer.inlineCallbacks
def get_external_ip():
    """
    Returns a deferred which will be called with a
    2-uple (wan_flag, ip_address):
        - wan_flag:
            - True if it's a WAN address
            - False if it's a LAN address
            - None if it's a localhost (127.0.0.1) address
        - ip_address: the most accessible ip address of this machine
    
    @return: A deferred called with the above defined tuple
    @rtype: L{twisted.internet.defer.Deferred}
    """
    
    try:
        local, ipaddr = yield get_local_ip()
    except:
        defer.returnValue((None, "127.0.0.1"))
    if not local:
        defer.returnValue((True, ipaddr))
    logging.debug("Got local ip, trying to use upnp to get WAN ip")
    import nattraverso.pynupnp
    try:
        ipaddr2 = yield nattraverso.pynupnp.get_external_ip()
    except:
        defer.returnValue((False, ipaddr))
    else:
        defer.returnValue((True, ipaddr2))

class _LocalNetworkMulticast(DatagramProtocol):
    def __init__(self, nonce):
        from p2pool.util import variable
        
        self.nonce = nonce
        self.address_received = variable.Event()
    
    def datagramReceived(self, dgram, addr):
        """Datagram received, we callback the IP address."""
        logging.debug("Received multicast pong: %s; addr:%r", dgram, addr)
        if dgram != self.nonce:
            return
        self.address_received.happened(addr[0])

@defer.inlineCallbacks
def _discover_multicast():
    """
    Local IP discovery protocol via multicast:
        - Broadcast 3 ping multicast packet with "ping" in it
        - Wait for an answer
        - Retrieve the ip address from the returning packet, which is ours
    """
    
    nonce = str(random.randrange(2**64))
    p = _LocalNetworkMulticast(nonce)
    
    for attempt in itertools.count():
        port = 11000 + random.randint(0, 5000)
        try:
            mcast = reactor.listenMulticast(port, p)
        except CannotListenError:
            if attempt >= 10:
                raise
            continue
        else:
            break
    
    try:
        yield mcast.joinGroup('239.255.255.250', socket.INADDR_ANY)
        
        logging.debug("Sending multicast ping")
        for i in xrange(3):
            p.transport.write(nonce, ('239.255.255.250', port))
        
        address, = yield p.address_received.get_deferred(5)
    finally:
        mcast.stopListening()
    
    defer.returnValue(address)
