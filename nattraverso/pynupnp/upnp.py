"""
This module is the heart of the upnp support. Device discover, ip discovery
and port mappings are implemented here.

@author: Raphael Slinckx
@author: Anthony Baxter
@copyright: Copyright 2005
@license: LGPL
@contact: U{raphael@slinckx.net<mailto:raphael@slinckx.net>}
@version: 0.1.0
"""
__revision__ = "$id"

import socket, random, urlparse, logging

from twisted.internet import reactor, defer
from twisted.web import client
from twisted.internet.protocol import DatagramProtocol
from twisted.internet.error import CannotListenError
from twisted.python import failure

from nattraverso.pynupnp.soap import SoapProxy
from nattraverso.pynupnp.upnpxml import UPnPXml
from nattraverso import ipdiscover, portmapper

class UPnPError(Exception):
    """
    A generic UPnP error, with a descriptive message as content.
    """
    pass

class UPnPMapper(portmapper.NATMapper):
    """
    This is the UPnP port mapper implementing the
    L{NATMapper<portmapper.NATMapper>} interface.
    
    @see: L{NATMapper<portmapper.NATMapper>}
    """
    
    def __init__(self, upnp):
        """
        Creates the mapper, with the given L{UPnPDevice} instance.
        
        @param upnp: L{UPnPDevice} instance
        """
        self._mapped = {}
        self._upnp = upnp
    
    def map(self, port):
        """
        See interface
        """
        self._check_valid_port(port)
        
        #Port is already mapped
        if port in self._mapped:
            return defer.succeed(self._mapped[port])
        
        #Trigger a new mapping creation, first fetch local ip.
        result = ipdiscover.get_local_ip()
        self._mapped[port] = result
        return result.addCallback(self._map_got_local_ip, port)
    
    def info(self, port):
        """
        See interface
        """
        # If the mapping exists, everything's ok
        if port in self._mapped:
            return self._mapped[port]
        else:
            raise ValueError('Port %r is not currently mapped'%(port))
    
    def unmap(self, port):
        """
        See interface
        """
        if port in self._mapped:
            existing = self._mapped[port]
            
            #Pending mapping, queue an unmap,return existing deferred
            if type(existing) is not tuple:
                existing.addCallback(lambda x: self.unmap(port))
                return existing
            
            #Remove our local mapping
            del self._mapped[port]
            
            #Ask the UPnP to remove the mapping
            extaddr, extport = existing
            return self._upnp.remove_port_mapping(extport, port.getHost().type)
        else:
            raise ValueError('Port %r is not currently mapped'%(port))
    
    def get_port_mappings(self):
        """
        See interface
        """
        return self._upnp.get_port_mappings()
    
    def _map_got_local_ip(self, ip_result, port):
        """
        We got the local ip address, retreive the existing port mappings
        in the device.
        
        @param ip_result: result of L{ipdiscover.get_local_ip}
        @param port: a L{twisted.internet.interfaces.IListeningPort} we
            want to map
        """
        local, ip = ip_result
        return self._upnp.get_port_mappings().addCallback(
            self._map_got_port_mappings, ip, port)
    
    def _map_got_port_mappings(self, mappings, ip, port):
        """
        We got all the existing mappings in the device, find an unused one
        and assign it for the requested port.
        
        @param ip: The local ip of this host "x.x.x.x"
        @param port: a L{twisted.internet.interfaces.IListeningPort} we
            want to map
        @param mappings: result of L{UPnPDevice.get_port_mappings}
        """
        
        #Get the requested mapping's info
        ptype = port.getHost().type
        intport = port.getHost().port
        
        for extport in [random.randrange(1025, 65536) for val in range(20)]:
            # Check if there is an existing mapping, if it does not exist, bingo
            if not (ptype, extport) in mappings:
                break
            
            if (ptype, extport) in mappings:
                existing = mappings[ptype, extport]
            
            local_ip, local_port = existing
            if local_ip == ip and local_port == intport:
                # Existing binding for this host/port/proto - replace it
                break
        
        # Triggers the creation of the mapping on the device
        result = self._upnp.add_port_mapping(ip, intport, extport, 'pynupnp', ptype)
        
        # We also need the external IP, so we queue first an
        # External IP Discovery, then we add the mapping.
        return result.addCallback(
            lambda x: self._upnp.get_external_ip()).addCallback(
                self._port_mapping_added, extport, port)
    
    def _port_mapping_added(self, extaddr, extport, port):
        """
        The port mapping was added in the device, this means::
            
            Internet        NAT         LAN
                |
        > IP:extaddr       |>       IP:local ip
            > Port:extport     |>       Port:port
                |
        
        @param extaddr: The exernal ip address
        @param extport: The external port as number
        @param port: The internal port as a
            L{twisted.internet.interfaces.IListeningPort} object, that has been
            mapped
        """
        self._mapped[port] = (extaddr, extport)
        return (extaddr, extport)

class UPnPDevice:
    """
    Represents an UPnP device, with the associated infos, and remote methods.
    """
    def __init__(self, soap_proxy, info):
        """
        Build the device, with the given SOAP proxy, and the meta-infos.
        
        @param soap_proxy: an initialized L{SoapProxy} to the device
        @param info: a dictionnary of various infos concerning the
            device extracted with L{UPnPXml}
        """
        self._soap_proxy = soap_proxy
        self._info = info
    
    def get_external_ip(self):
        """
        Triggers an external ip discovery on the upnp device. Returns
        a deferred called with the external ip of this host.
        
        @return: A deferred called with the ip address, as "x.x.x.x"
        @rtype: L{twisted.internet.defer.Deferred}
        """
        result = self._soap_proxy.call('GetExternalIPAddress')
        result.addCallback(self._on_external_ip)
        return result
    
    def get_port_mappings(self):
        """
        Retreive the existing port mappings
        
        @see: L{portmapper.NATMapper.get_port_mappings}
        @return: A deferred called with the dictionnary as defined
            in the interface L{portmapper.NATMapper.get_port_mappings}
        @rtype: L{twisted.internet.defer.Deferred}
        """
        return self._get_port_mapping()
    
    def add_port_mapping(self, local_ip, intport, extport, desc, proto, lease=0):
        """
        Add a port mapping in the upnp device. Returns a deferred.
        
        @param local_ip: the LAN ip of this host as "x.x.x.x"
        @param intport: the internal port number
        @param extport: the external port number
        @param desc: the description of this mapping (string)
        @param proto: "UDP" or "TCP"
        @param lease: The duration of the lease in (mili)seconds(??)
        @return: A deferred called with None when the mapping is done
        @rtype: L{twisted.internet.defer.Deferred}
        """
        result = self._soap_proxy.call('AddPortMapping', NewRemoteHost="",
            NewExternalPort=extport,
            NewProtocol=proto,
            NewInternalPort=intport,
            NewInternalClient=local_ip,
            NewEnabled=1,
            NewPortMappingDescription=desc,
            NewLeaseDuration=lease)
        
        return result.addCallbacks(self._on_port_mapping_added,
            self._on_no_port_mapping_added)
    
    def remove_port_mapping(self, extport, proto):
        """
        Remove an existing port mapping on the device. Returns a deferred
        
        @param extport: the external port number associated to the mapping
            to be removed
        @param proto: either "UDP" or "TCP"
        @return: A deferred called with None when the mapping is done
        @rtype: L{twisted.internet.defer.Deferred}
        """
        result = self._soap_proxy.call('DeletePortMapping', NewRemoteHost="",
            NewExternalPort=extport,
            NewProtocol=proto)
        
        return result.addCallbacks(self._on_port_mapping_removed,
            self._on_no_port_mapping_removed)
    
    # Private --------
    def _on_external_ip(self, res):
        """
        Called when we received the external ip address from the device.
        
        @param res: the SOAPpy structure of the result
        @return: the external ip string, as "x.x.x.x"
        """
        logging.debug("Got external ip struct: %r", res)
        return res['NewExternalIPAddress']
    
    def _get_port_mapping(self, mapping_id=0, mappings=None):
        """
        Fetch the existing mappings starting at index
        "mapping_id" from the device.
        
        To retreive all the mappings call this without parameters.
        
        @param mapping_id: The index of the mapping to start fetching from
        @param mappings: the dictionnary of already fetched mappings
        @return: A deferred called with the existing mappings when all have been
            retreived, see L{get_port_mappings}
        @rtype: L{twisted.internet.defer.Deferred}
        """
        if mappings == None:
            mappings = {}
        
        result = self._soap_proxy.call('GetGenericPortMappingEntry',
            NewPortMappingIndex=mapping_id)
        return result.addCallbacks(
            lambda x: self._on_port_mapping_received(x, mapping_id+1, mappings),
            lambda x: self._on_no_port_mapping_received(        x, mappings))
    
    def _on_port_mapping_received(self, response, mapping_id, mappings):
        """
        Called we we receive a single mapping from the device.
        
        @param response: a SOAPpy structure, representing the device's answer
        @param mapping_id: The index of the next mapping in the device
        @param mappings: the already fetched mappings, see L{get_port_mappings}
        @return: A deferred called with the existing mappings when all have been
            retreived, see L{get_port_mappings}
        @rtype: L{twisted.internet.defer.Deferred}
        """
        logging.debug("Got mapping struct: %r", response)
        mappings[
            response['NewProtocol'], response['NewExternalPort']
        ] = (response['NewInternalClient'], response['NewInternalPort'])
        return self._get_port_mapping(mapping_id, mappings)
    
    def _on_no_port_mapping_received(self, failure, mappings):
        """
        Called when we have no more port mappings to retreive, or an
        error occured while retreiving them.
        
        Either we have a "SpecifiedArrayIndexInvalid" SOAP error, and that's ok,
        it just means we have finished. If it returns some other error, then we
        fail with an UPnPError.
        
        @param mappings: the already retreived mappings
        @param failure: the failure
        @return: The existing mappings as defined in L{get_port_mappings}
        @raise UPnPError: When we got any other error
            than "SpecifiedArrayIndexInvalid"
        """
        logging.debug("_on_no_port_mapping_received: %s", failure)
        err = failure.value
        message = err.args[0]["UPnPError"]["errorDescription"]
        if "SpecifiedArrayIndexInvalid" == message:
            return mappings
        else:
            return failure
    
    
    def _on_port_mapping_added(self, response):
        """
        The port mapping was successfully added, return None to the deferred.
        """
        return None
    
    def _on_no_port_mapping_added(self, failure):
        """
        Called when the port mapping could not be added. Immediately
        raise an UPnPError, with the SOAPpy structure inside.
        
        @raise UPnPError: When the port mapping could not be added
        """
        return failure
    
    def _on_port_mapping_removed(self, response):
        """
        The port mapping was successfully removed, return None to the deferred.
        """
        return None
    
    def _on_no_port_mapping_removed(self, failure):
        """
        Called when the port mapping could not be removed. Immediately
        raise an UPnPError, with the SOAPpy structure inside.
        
        @raise UPnPError: When the port mapping could not be deleted
        """
        return failure

# UPNP multicast address, port and request string
_UPNP_MCAST = '239.255.255.250'
_UPNP_PORT = 1900
_UPNP_SEARCH_REQUEST = """M-SEARCH * HTTP/1.1\r
Host:%s:%s\r
ST:urn:schemas-upnp-org:device:InternetGatewayDevice:1\r
Man:"ssdp:discover"\r
MX:3\r
\r
""" % (_UPNP_MCAST, _UPNP_PORT)

class UPnPProtocol(DatagramProtocol, object):
    """
    The UPnP Device discovery udp multicast twisted protocol.
    """
    
    def __init__(self, *args, **kwargs):
        """
        Init the protocol, no parameters needed.
        """
        super(UPnPProtocol, self).__init__(*args, **kwargs)
        
        #Device discovery deferred
        self._discovery = None
        self._discovery_timeout = None
        self.mcast = None
        self._done = False
    
    # Public methods
    def search_device(self):
        """
        Triggers a UPnP device discovery.
        
        The returned deferred will be called with the L{UPnPDevice} that has
        been found in the LAN.
        
        @return: A deferred called with the detected L{UPnPDevice} instance.
        @rtype: L{twisted.internet.defer.Deferred}
        """
        if self._discovery is not None:
            raise ValueError('already used')
        self._discovery = defer.Deferred()
        self._discovery_timeout = reactor.callLater(6, self._on_discovery_timeout)
        
        attempt = 0
        mcast = None
        while True:
            try:
                self.mcast = reactor.listenMulticast(1900+attempt, self)
                break
            except CannotListenError:
                attempt = random.randint(0, 500)
        
        # joined multicast group, starting upnp search
        self.mcast.joinGroup('239.255.255.250', socket.INADDR_ANY)
        
        self.transport.write(_UPNP_SEARCH_REQUEST, (_UPNP_MCAST, _UPNP_PORT))
        self.transport.write(_UPNP_SEARCH_REQUEST, (_UPNP_MCAST, _UPNP_PORT))
        self.transport.write(_UPNP_SEARCH_REQUEST, (_UPNP_MCAST, _UPNP_PORT))
        
        return self._discovery
    
    #Private methods
    def datagramReceived(self, dgram, address):
        if self._done:
            return
        """
        This is private, handle the multicast answer from the upnp device.
        """
        logging.debug("Got UPNP multicast search answer:\n%s", dgram)
        
        #This is an HTTP response
        response, message = dgram.split('\r\n', 1)
        
        # Prepare status line
        version, status, textstatus = response.split(None, 2)
        
        if not version.startswith('HTTP'):
            return
        if status != "200":
            return
        
        # Launch the info fetching
        def parse_discovery_response(message):
            """Separate headers and body from the received http answer."""
            hdict = {}
            body = ''
            remaining = message
            while remaining:
                line, remaining = remaining.split('\r\n', 1)
                line = line.strip()
                if not line:
                    body = remaining
                    break
                key, val = line.split(':', 1)
                key = key.lower()
                hdict.setdefault(key, []).append(val.strip())
            return hdict, body
        
        headers, body = parse_discovery_response(message)
        
        if not 'location' in headers:
            self._on_discovery_failed(
                UPnPError(
                    "No location header in response to M-SEARCH!: %r"%headers))
            return
        
        loc = headers['location'][0]
        result = client.getPage(url=loc)
        result.addCallback(self._on_gateway_response, loc).addErrback(self._on_discovery_failed)
    
    def _on_gateway_response(self, body, loc):
        if self._done:
            return
        """
        Called with the UPnP device XML description fetched via HTTP.
        
        If the device has suitable services for ip discovery and port mappings,
        the callback returned in L{search_device} is called with
        the discovered L{UPnPDevice}.
        
        @raise UPnPError: When no suitable service has been
            found in the description, or another error occurs.
        @param body: The xml description of the device.
        @param loc: the url used to retreive the xml description
        """
        
        # Parse answer
        upnpinfo = UPnPXml(body)
        
        # Check if we have a base url, if not consider location as base url
        urlbase = upnpinfo.urlbase
        if urlbase == None:
            urlbase = loc
        
        # Check the control url, if None, then the device cannot do what we want
        controlurl = upnpinfo.controlurl
        if controlurl == None:
            self._on_discovery_failed(UPnPError("upnp response showed no WANConnections"))
            return
        
        control_url2 = urlparse.urljoin(urlbase, controlurl)
        soap_proxy = SoapProxy(control_url2, upnpinfo.wanservice)
        self._on_discovery_succeeded(UPnPDevice(soap_proxy, upnpinfo.deviceinfos))
    
    def _on_discovery_succeeded(self, res):
        if self._done:
            return
        self._done = True
        self.mcast.stopListening()
        self._discovery_timeout.cancel()
        self._discovery.callback(res)
    
    def _on_discovery_failed(self, err):
        if self._done:
            return
        self._done = True
        self.mcast.stopListening()
        self._discovery_timeout.cancel()
        self._discovery.errback(err)
    
    def _on_discovery_timeout(self):
        if self._done:
            return
        self._done = True
        self.mcast.stopListening()
        self._discovery.errback(failure.Failure(defer.TimeoutError('in _on_discovery_timeout')))

def search_upnp_device ():
    """
    Check the network for an UPnP device. Returns a deferred
    with the L{UPnPDevice} instance as result, if found.
    
    @return: A deferred called with the L{UPnPDevice} instance
    @rtype: L{twisted.internet.defer.Deferred}
    """
    return defer.maybeDeferred(UPnPProtocol().search_device)
