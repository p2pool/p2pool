"""
Various utility functions used in the nattraverso package.

@author: Raphael Slinckx
@copyright: Copyright 2005
@license: LGPL
@contact: U{raphael@slinckx.net<mailto:raphael@slinckx.net>}
@version: 0.1.0
"""
__revision__ = "$id"

def is_rfc1918_ip(ip):
    """
    Checks if the given ip address is a rfc1918 one.
    
    @param ip: The ip address to test
    @type ip: a string "x.x.x.x"
    @return: True if it's a LAN address, False otherwise
    """
    if isinstance(ip, basestring):
        ip = _ip_to_number(ip)
    
    for net, mask in _nets:
        if ip&mask == net:
            return True
    
    return False

def is_bogus_ip(ip):
    """
    Checks if the given ip address is bogus, i.e. 0.0.0.0 or 127.0.0.1.
    
    @param ip: The ip address to test
    @type ip: a string "x.x.x.x"
    @return: True if it's bogus, False otherwise
    """
    return ip.startswith('0.') or ip.startswith('127.')

def _ip_to_number(ipstr):
    """
    Translate a string ip address to a packed number.
    
    @param ipstr: the ip address to transform
    @type ipstr: a string "x.x.x.x"
    @return: an int32 number representing the ip address
    """
    net = [ int(digit) for digit in ipstr.split('.') ] + [ 0, 0, 0 ]
    net = net[:4]
    return  ((((((0L+net[0])<<8) + net[1])<<8) + net[2])<<8) +net[3]

# List of rfc1918 net/mask
_rfc1918_networks = [('127', 8), ('192.168', 16), ('10', 8), ('172.16', 12)]
# Machine readable form of the above
_nets = [(_ip_to_number(net), (2L**32 -1)^(2L**(32-mask)-1))
    for net, mask in _rfc1918_networks]

