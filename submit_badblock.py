import base64

from twisted.internet import defer, reactor
from twisted.web import resource, server

from p2pool import networks
from p2pool.bitcoin import data, worker_interface, getwork, helper
from p2pool.util import jsonrpc, variable

@defer.inlineCallbacks
def main():
    bitcoind = jsonrpc.Proxy('http://127.0.0.1:8332/', dict(Authorization='Basic ' + base64.b64encode(':password')))
    block = data.block_type.unpack(open('badblock').read())
    yield helper.submit_block_rpc(block, False, bitcoind, variable.Variable(dict(use_getblocktemplate=True)), networks.nets['bitcoin'])
    reactor.stop()

main()
reactor.run()
