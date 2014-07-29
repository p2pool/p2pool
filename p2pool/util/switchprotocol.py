from twisted.internet import protocol

class FirstByteSwitchProtocol(protocol.Protocol):
    p = None
    def dataReceived(self, data):
        if self.p is None:
            if not data: return
            serverfactory = self.factory.first_byte_to_serverfactory.get(data[0], self.factory.default_serverfactory)
            self.p = serverfactory.buildProtocol(self.transport.getPeer())
            self.p.makeConnection(self.transport)
        self.p.dataReceived(data)
    def connectionLost(self, reason):
        if self.p is not None:
            self.p.connectionLost(reason)

class FirstByteSwitchFactory(protocol.ServerFactory):
    protocol = FirstByteSwitchProtocol
    
    def __init__(self, first_byte_to_serverfactory, default_serverfactory):
        self.first_byte_to_serverfactory = first_byte_to_serverfactory
        self.default_serverfactory = default_serverfactory
    
    def startFactory(self):
        for f in list(self.first_byte_to_serverfactory.values()) + [self.default_serverfactory]:
            f.doStart()
    
    def stopFactory(self):
        for f in list(self.first_byte_to_serverfactory.values()) + [self.default_serverfactory]:
            f.doStop()
