"""
Generic NAT Port mapping interface.

TODO: Example

@author: Raphael Slinckx
@copyright: Copyright 2005
@license: LGPL
@contact: U{raphael@slinckx.net<mailto:raphael@slinckx.net>}
@version: 0.1.0
"""

__revision__ = "$id"

from twisted.internet.base import BasePort

# Public API
def get_port_mapper(proto="TCP"):
    """
    Returns a L{NATMapper} instance, suited to map a port for
    the given protocol. Defaults to TCP.
    
    For the moment, only upnp mapper is available. It accepts both UDP and TCP.
    
    @param proto: The protocol: 'TCP' or 'UDP'
    @type proto: string
    @return: A deferred called with a L{NATMapper} instance
    @rtype: L{twisted.internet.defer.Deferred}
    """
    import nattraverso.pynupnp
    return nattraverso.pynupnp.get_port_mapper()

class NATMapper:
    """
    Define methods to map port objects (as returned by twisted's listenXX).
    This allows NAT to be traversed from incoming packets.
    
    Currently the only implementation of this class is the UPnP Mapper, which
    can map UDP and TCP ports, if an UPnP Device exists.
    """
    def __init__(self):
        raise NotImplementedError("Cannot instantiate the class")
    
    def map(self, port):
        """
        Create a mapping for the given twisted's port object.
        
        The deferred will call back with a tuple (extaddr, extport):
            - extaddr: The ip string of the external ip address of this host
            - extport: the external port number used to map the given Port object
        
        When called multiple times with the same Port,
        callback with the existing mapping.
        
        @param port: The port object to map
        @type port: a L{twisted.internet.interfaces.IListeningPort} object
        @return: A deferred called with the above defined tuple
        @rtype: L{twisted.internet.defer.Deferred}
        """
        raise NotImplementedError
    
    def info(self, port):
        """
        Returns the existing mapping for the given port object. That means map()
        has to be called before.
        
        @param port: The port object to retreive info from
        @type port: a L{twisted.internet.interfaces.IListeningPort} object
        @raise ValueError: When there is no such existing mapping
        @return: a tuple (extaddress, extport).
        @see: L{map() function<map>}
        """
        raise NotImplementedError
    
    def unmap(self, port):
        """
        Remove an existing mapping for the given twisted's port object.
        
        @param port: The port object to unmap
        @type port: a L{twisted.internet.interfaces.IListeningPort} object
        @return: A deferred called with None
        @rtype: L{twisted.internet.defer.Deferred}
        @raise ValueError: When there is no such existing mapping
        """
        raise NotImplementedError
    
    def get_port_mappings(self):
        """
        Returns a deferred that will be called with a dictionnary of the
        existing mappings.
        
        The dictionnary structure is the following:
            - Keys: tuple (protocol, external_port)
                - protocol is "TCP" or "UDP".
                - external_port is the external port number, as see on the
                    WAN side.
            - Values:tuple (internal_ip, internal_port)
                - internal_ip is the LAN ip address of the host.
                - internal_port is the internal port number mapped
                    to external_port.
        
        @return: A deferred called with the above defined dictionnary
        @rtype: L{twisted.internet.defer.Deferred}
        """
        raise NotImplementedError
    
    def _check_valid_port(self, port):
        """Various Port object validity checks. Raise a ValueError."""
        if not isinstance(port, BasePort):
            raise ValueError("expected a Port, got %r"%(port))
        
        if not port.connected:
            raise ValueError("Port %r is not listening"%(port))
        
        loc_addr = port.getHost()
        if loc_addr.port == 0:
            raise ValueError("Port %r has port number of 0"%(port))

