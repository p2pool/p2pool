"""
This module parse an UPnP device's XML definition in an Object.

@author: Raphael Slinckx
@copyright: Copyright 2005
@license: LGPL
@contact: U{raphael@slinckx.net<mailto:raphael@slinckx.net>}
@version: 0.1.0
"""

__revision__ = "$id"

from xml.dom import minidom
import logging

# Allowed UPnP services to use when mapping ports/external addresses
WANSERVICES = ['urn:schemas-upnp-org:service:WANIPConnection:1',
    'urn:schemas-upnp-org:service:WANPPPConnection:1']

class UPnPXml:
    """
    This objects parses the XML definition, and stores the useful
    results in attributes.
    
    The device infos dictionnary may contain the following keys:
        - friendlyname: A friendly name to call the device.
        - manufacturer: A manufacturer name for the device.
    
    Here are the different attributes:
        - deviceinfos: A dictionnary of device infos as defined above.
        - controlurl: The control url, this is the url to use when sending SOAP
            requests to the device, relative to the base url.
        - wanservice: The WAN service to be used, one of the L{WANSERVICES}
        - urlbase: The base url to use when talking in SOAP to the device.
    
    The full url to use is obtained by urljoin(urlbase, controlurl)
    """
    
    def __init__(self, xml):
        """
        Parse the given XML string for UPnP infos. This creates the attributes
        when they are found, or None if no value was found.
        
        @param xml: a xml string to parse
        """
        logging.debug("Got UPNP Xml description:\n%s", xml)
        doc = minidom.parseString(xml)
        
        # Fetch various device info
        self.deviceinfos = {}
        try:
            attributes = {
                'friendlyname':'friendlyName',
                'manufacturer' : 'manufacturer'
            }
            device = doc.getElementsByTagName('device')[0]
            for name, tag in attributes.iteritems():
                try:
                    self.deviceinfos[name] = device.getElementsByTagName(
                        tag)[0].firstChild.datas.encode('utf-8')
                except:
                    pass
        except:
            pass
        
        # Fetch device control url
        self.controlurl = None
        self.wanservice = None
        
        for service in doc.getElementsByTagName('service'):
            try:
                stype = service.getElementsByTagName(
                    'serviceType')[0].firstChild.data.encode('utf-8')
                if stype in WANSERVICES:
                    self.controlurl = service.getElementsByTagName(
                        'controlURL')[0].firstChild.data.encode('utf-8')
                    self.wanservice = stype
                    break
            except:
                pass
        
        # Find base url
        self.urlbase = None
        try:
            self.urlbase = doc.getElementsByTagName(
                'URLBase')[0].firstChild.data.encode('utf-8')
        except:
            pass

