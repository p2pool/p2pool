"""
This package offers ways to retreive ip addresses of the machine, and map ports
through UPnP devices.

@author: Raphael Slinckx
@copyright: Copyright 2005
@license: LGPL
@contact: U{raphael@slinckx.net<mailto:raphael@slinckx.net>}
@version: 0.1.0
"""
__revision__ = "$id"

from nattraverso.pynupnp.upnp import search_upnp_device, UPnPMapper

def get_external_ip():
    """
    Returns a deferred which will be called with the WAN ip address
    retreived through UPnP. The ip is a string of the form "x.x.x.x"
    
    @return: A deferred called with the external ip address of this host
    @rtype: L{twisted.internet.defer.Deferred}
    """
    return search_upnp_device().addCallback(lambda x: x.get_external_ip())

def get_port_mapper():
    """
    Returns a deferred which will be called with a L{UPnPMapper} instance.
    This is a L{nattraverso.portmapper.NATMapper} implementation.
    
    @return: A deferred called with the L{UPnPMapper} instance.
    @rtype: L{twisted.internet.defer.Deferred}
    """
    return search_upnp_device().addCallback(lambda x: UPnPMapper(x))
