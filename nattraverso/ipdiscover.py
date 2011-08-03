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

import random, socket, logging

from twisted.internet import defer, reactor

from twisted.internet.protocol import DatagramProtocol
from twisted.internet.error import CannotListenError
from twisted.internet.interfaces import IReactorMulticast

from nattraverso.utils import is_rfc1918_ip, is_bogus_ip

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
	result = reactor.resolve('A.ROOT-SERVERS.NET')
	result.addCallbacks(_get_via_connected_udp, lambda x:_get_via_multicast())
	return result

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
	return get_local_ip().addCallbacks(_on_local_ip, _on_no_local_ip)
	
#Private----------
def _on_upnp_external_found(ipaddr):
	"""
	Called when an external ip is found through UPNP.
	
	@param ipaddr: The WAN ip address
	@type ipaddr: an IP string "x.x.x.x"
	"""
	return (True, ipaddr)

def _on_no_upnp_external_found(error, ipaddr):
	"""
	Called when the UPnP device failed to return external address.
	
	@param ipaddr: The LAN ip address
	@type ipaddr: an IP string "x.x.x.x"
	"""
	return (False, ipaddr)
	
def _on_local_ip(result):
	"""
	Called when we got the local ip of this machine. If we have a WAN address,
	we return immediately, else we try to discover ip address through UPnP.
	
	@param result: a tuple (lan_flag, ip_addr)
	@type result: a tuple (bool, ip string)
	"""
	local, ipaddr = result
	if not local:
		return (True, ipaddr)
	else:
		logging.debug("Got local ip, trying to use upnp to get WAN ip")
		import nattraverso.pynupnp
		return nattraverso.pynupnp.get_external_ip().addCallbacks(
			_on_upnp_external_found,
			lambda x: _on_no_upnp_external_found(x, ipaddr))

def _on_no_local_ip(error):
	"""
	Called when we could not retreive by any mean the ip of this machine.
	We simply assume there is no connectivity, and return localhost address.
	"""
	return (None, "127.0.0.1")
	
def _got_multicast_ip(ipaddr):
	"""
	Called when we received the ip address via udp multicast.
	
	@param ipaddr: an ip address
	@type ipaddr: a string "x.x.x.x"
	"""
	return (is_rfc1918_ip(ipaddr), ipaddr)

def _get_via_multicast():
	"""
	Init a multicast ip address discovery.
	
	@return: A deferred called with the discovered ip address
	@rtype: L{twisted.internet.defer.Deferred}
	@raise Exception: When an error occurs during the multicast engine init
	"""
	try:
		# Init multicast engine
		IReactorMulticast(reactor)
	except:
		raise

	logging.debug("Multicast ping to retreive local IP")
	return LocalNetworkMulticast().discover().addCallback(_got_multicast_ip)

def _get_via_connected_udp(ipaddr):
	"""
	Init a UDP socket ip discovery. We do a dns query, and retreive our
	ip address from the connected udp socket.
	
	@param ipaddr: The ip address of a dns server
	@type ipaddr: a string "x.x.x.x"
	@raise RuntimeError: When the ip is a bogus ip (0.0.0.0 or alike)
	"""
	udpprot = DatagramProtocol()
	port = reactor.listenUDP(0, udpprot)
	udpprot.transport.connect(ipaddr, 7)
	localip = udpprot.transport.getHost().host
	port.stopListening()
	
	if is_bogus_ip(localip):
		raise RuntimeError, "Invalid IP addres returned"
	else:
		return (is_rfc1918_ip(localip), localip)
		
class LocalNetworkMulticast(DatagramProtocol, object):
	"""
	Local IP discovery protocol via multicast:
		- Broadcast 3 ping multicast packet with "ping" in it
		- Wait for an answer
		- Retreive the ip address from the returning packet, which is ours
	"""
	def __init__(self, *args, **kwargs):
		super(LocalNetworkMulticast, self).__init__(*args, **kwargs)
		
		# Nothing found yet
		self.completed = False
		self.result = defer.Deferred()
		
	def discover(self):
		"""
		Launch the discovery of an UPnP device on the local network. You should
		always call this after having created the object.
		
		>>> result = LocalNetworkMulticast().discover().addCallback(got_upnpdevice_ip)
		
		@return: A deferred called with the IP address of the UPnP device
		@rtype: L{twisted.internet.defer.Deferred}
		"""
		#The port we listen on
		mcast_port = 0
		#The result of listenMulticast
		mcast = None

		# 5 different UDP ports
		ports = [11000+random.randint(0, 5000) for port in range(5)]
		for attempt, port in enumerate(ports):
			try:
				mcast = reactor.listenMulticast(port, self)
				mcast_port = port
				break
			except CannotListenError:
				if attempt < 5:
					print "Trying another multicast UDP port", port
				else:
					raise
		
		logging.debug("Sending multicast ping")
		mcast.joinGroup('239.255.255.250', socket.INADDR_ANY)
		self.transport.write('ping', ('239.255.255.250', mcast_port))
		self.transport.write('ping', ('239.255.255.250', mcast_port))
		self.transport.write('ping', ('239.255.255.250', mcast_port))
		return self.result

	def datagramReceived(self, dgram, addr):
		"""Datagram received, we callback the IP address."""
		logging.debug("Received multicast pong: %s; addr:%r", dgram, addr)
		if self.completed or dgram != 'ping':
			# Result already handled, do nothing
			return
		else:
			self.completed = True
			# Return the upn device ip address
			self.result.callback(addr[0])
