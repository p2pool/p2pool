"""
This module is a SOAP client using twisted's deferreds.
It uses the SOAPpy package.

@author: Raphael Slinckx
@copyright: Copyright 2005
@license: LGPL
@contact: U{raphael@slinckx.net<mailto:raphael@slinckx.net>}
@version: 0.1.0
"""

__revision__ = "$id"

import SOAPpy, logging
from SOAPpy.Config import Config
from twisted.web import client, error

#General config
Config.typed = False

class SoapError(Exception):
    """
    This is a SOAP error message, not an HTTP error message.
    
    The content of this error is a SOAPpy structure representing the
    SOAP error message.
    """
    pass

class SoapProxy:
    """
    Proxy for an url to which we send SOAP rpc calls.
    """
    def __init__(self, url, prefix):
        """
        Init the proxy, it will connect to the given url, using the
        given soap namespace.
        
        @param url: The url of the remote host to call
        @param prefix: The namespace prefix to use, eg.
            'urn:schemas-upnp-org:service:WANIPConnection:1'
        """
        logging.debug("Soap Proxy: '%s', prefix: '%s'", url, prefix)
        self._url = url
        self._prefix = prefix
    
    def call(self, method, **kwargs):
        """
        Call the given remote method with the given arguments, as keywords.
        
        Returns a deferred, called with SOAPpy structure representing
        the soap response.
        
        @param method: The method name to call, eg. 'GetExternalIP'
        @param kwargs: The parameters of the call, as keywords
        @return: A deferred called with the external ip address of this host
        @rtype: L{twisted.internet.defer.Deferred}
        """
        payload = SOAPpy.buildSOAP(method=method, config=Config, namespace=self._prefix, kw=kwargs)
        # Here begins the nasty hack
        payload = payload.replace(
            # Upnp wants s: instead of SOAP-ENV
            'SOAP-ENV','s').replace(
            # Doesn't seem to like these encoding stuff
            'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/"', '').replace(
            'SOAP-ENC:root="1"', '').replace(
            # And it wants u: instead of ns1 namespace for arguments..
            'ns1','u')
        
        logging.debug("SOAP Payload:\n%s", payload)
        
        return client.getPage(self._url, postdata=payload, method="POST",
            headers={'content-type': 'text/xml',        'SOAPACTION': '%s#%s' % (self._prefix, method)}
    ).addCallbacks(self._got_page, self._got_error)
    
    def _got_page(self, result):
        """
        The http POST command was successful, we parse the SOAP
        answer, and return it.
        
        @param result: the xml content
        """
        parsed = SOAPpy.parseSOAPRPC(result)
        
        logging.debug("SOAP Answer:\n%s", result)
        logging.debug("SOAP Parsed Answer: %r", parsed)
        
        return parsed
    
    def _got_error(self, res):
        """
        The HTTP POST command did not succeed, depending on the error type:
            - it's a SOAP error, we parse it and return a L{SoapError}.
            - it's another type of error (http, other), we raise it as is
        """
        logging.debug("SOAP Error:\n%s", res)
        
        if isinstance(res.value, error.Error):
            try:
                logging.debug("SOAP Error content:\n%s", res.value.response)
                raise SoapError(SOAPpy.parseSOAPRPC(res.value.response)["detail"])
            except:
                raise
        raise Exception(res.value)
