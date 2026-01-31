import random
import sys
import time

from twisted.internet import protocol, reactor
from twisted.python import log

from p2pool.bitcoin import data as bitcoin_data, getwork
from p2pool.util import expiring_dict, jsonrpc, pack

def clip(num, bot, top):
    return min(top, max(bot, num))

class StratumRPCMiningProvider(object):
    def __init__(self, wb, other, transport):
        self.pool_version_mask = 0x1fffe000
        self.wb = wb
        self.other = other
        self.transport = transport
        
        self.username = None
        self.handler_map = expiring_dict.ExpiringDict(300)
        
        self.watch_id = self.wb.new_work_event.watch(self._send_work)

        self.recent_shares = []
        self.target = None
        self.share_rate = wb.share_rate
        self.fixed_target = False
        self.desired_pseudoshare_target = None

    
    def rpc_subscribe(self, miner_version=None, session_id=None, *args):
        reactor.callLater(0, self._send_work)
        
        return [
            ["mining.notify", "ae6812eb4cd7735a302a8a9dd95cf71f"], # subscription details
            "", # extranonce1
            self.wb.COINBASE_NONCE_LENGTH, # extranonce2_size
        ]
    
    def rpc_authorize(self, username, password):
        if not hasattr(self, 'authorized'): # authorize can be called many times in one connection
            print '>>>Authorize: %s from %s' % (username, self.transport.getPeer().host)
            self.authorized = username
        self.username = username.strip()
        
        self.user, self.address, self.desired_share_target, self.desired_pseudoshare_target = self.wb.get_user_details(username)
        reactor.callLater(0, self._send_work)
        return True

    def rpc_configure(self, extensions, extensionParameters):
        #extensions is a list of extension codes defined in BIP310
        #extensionParameters is a dict of parameters for each extension code
        if 'version-rolling' in extensions:
            #mask from miner is mandatory but we dont use it
            miner_mask = extensionParameters['version-rolling.mask']
            #min-bit-count from miner is mandatory but we dont use it
            try:
                minbitcount = extensionParameters['version-rolling.min-bit-count']
            except:
                log.err("A miner tried to connect with a malformed version-rolling.min-bit-count parameter. This is probably a bug in your mining software. Braiins OS is known to have this bug. You should complain to them.")
                minbitcount = 2 # probably not needed
            #according to the spec, pool should return largest mask possible (to support mining proxies)
            return {"version-rolling" : True, "version-rolling.mask" : '{:08x}'.format(self.pool_version_mask&(int(miner_mask,16)))}
            #pool can send mining.set_version_mask at any time if the pool mask changes

        if 'minimum-difficulty' in extensions:
            print 'Extension method minimum-difficulty not implemented'
        if 'subscribe-extranonce' in extensions:
            print 'Extension method subscribe-extranonce not implemented'

    def _send_work(self):
        try:
            x, got_response = self.wb.get_work(*self.wb.preprocess_request('' if self.username is None else self.username))
        except:
            log.err()
            self.transport.loseConnection()
            return
        if self.desired_pseudoshare_target:
            self.fixed_target = True
            self.target = self.desired_pseudoshare_target
            self.target = max(self.target, int(x['bits'].target))
        else:
            self.fixed_target = False
            self.target = x['share_target'] if self.target == None else max(x['min_share_target'], self.target)
        jobid = str(random.randrange(2**128))
        self.other.svc_mining.rpc_set_difficulty(bitcoin_data.target_to_difficulty(self.target)*self.wb.net.DUMB_SCRYPT_DIFF).addErrback(lambda err: None)
        self.other.svc_mining.rpc_notify(
            jobid, # jobid
            getwork._swap4(pack.IntType(256).pack(x['previous_block'])).encode('hex'), # prevhash
            x['coinb1'].encode('hex'), # coinb1
            x['coinb2'].encode('hex'), # coinb2
            [pack.IntType(256).pack(s).encode('hex') for s in x['merkle_link']['branch']], # merkle_branch
            getwork._swap4(pack.IntType(32).pack(x['version'])).encode('hex'), # version
            getwork._swap4(pack.IntType(32).pack(x['bits'].bits)).encode('hex'), # nbits
            getwork._swap4(pack.IntType(32).pack(x['timestamp'])).encode('hex'), # ntime
            True, # clean_jobs
        ).addErrback(lambda err: None)
        self.handler_map[jobid] = x, got_response
    
    def rpc_submit(self, worker_name, job_id, extranonce2, ntime, nonce, version_bits = None, *args):
        #asicboost: version_bits is the version mask that the miner used
        worker_name = worker_name.strip()
        if job_id not in self.handler_map:
            print >>sys.stderr, '''Couldn't link returned work's job id with its handler. This should only happen if this process was recently restarted!'''
            #self.other.svc_client.rpc_reconnect().addErrback(lambda err: None)
            return False
        x, got_response = self.handler_map[job_id]
        coinb_nonce = extranonce2.decode('hex')
        assert len(coinb_nonce) == self.wb.COINBASE_NONCE_LENGTH
        new_packed_gentx = x['coinb1'] + coinb_nonce + x['coinb2']

        job_version = x['version']
        nversion = job_version
        #check if miner changed bits that they were not supposed to change
        if version_bits:
            if ((~self.pool_version_mask) & int(version_bits,16)) != 0:
                #todo: how to raise error back to miner?
                #protocol does not say error needs to be returned but ckpool returns
                #{"error": "Invalid version mask", "id": "id", "result":""}
                raise ValueError("Invalid version mask {0}".format(version_bits))
            nversion = (job_version & ~self.pool_version_mask) | (int(version_bits,16) & self.pool_version_mask)
            #nversion = nversion & int(version_bits,16)

        header = dict(
            version=nversion,
            previous_block=x['previous_block'],
            merkle_root=bitcoin_data.check_merkle_link(bitcoin_data.hash256(new_packed_gentx), x['merkle_link']), # new_packed_gentx has witness data stripped
            timestamp=pack.IntType(32).unpack(getwork._swap4(ntime.decode('hex'))),
            bits=x['bits'],
            nonce=pack.IntType(32).unpack(getwork._swap4(nonce.decode('hex'))),
        )
        result = got_response(header, worker_name, coinb_nonce, self.target)

        # adjust difficulty on this stratum to target ~10sec/pseudoshare
        if not self.fixed_target:
            self.recent_shares.append(time.time())
            if len(self.recent_shares) > 12 or (time.time() - self.recent_shares[0]) > 10*len(self.recent_shares)*self.share_rate:
                old_time = self.recent_shares[0]
                del self.recent_shares[0]
                olddiff = bitcoin_data.target_to_difficulty(self.target)
                self.target = int(self.target * clip((time.time() - old_time)/(len(self.recent_shares)*self.share_rate), 0.5, 2.) + 0.5)
                newtarget = clip(self.target, self.wb.net.SANE_TARGET_RANGE[0], self.wb.net.SANE_TARGET_RANGE[1])
                if newtarget != self.target:
                    print "Clipping target from %064x to %064x" % (self.target, newtarget)
                    self.target = newtarget
                self.target = max(x['min_share_target'], self.target)
                self.recent_shares = [time.time()]
                self._send_work()

        return result

    
    def close(self):
        self.wb.new_work_event.unwatch(self.watch_id)

class StratumProtocol(jsonrpc.LineBasedPeer):
    def connectionMade(self):
        self.svc_mining = StratumRPCMiningProvider(self.factory.wb, self.other, self.transport)
    
    def connectionLost(self, reason):
        self.svc_mining.close()

class StratumServerFactory(protocol.ServerFactory):
    protocol = StratumProtocol
    
    def __init__(self, wb):
        self.wb = wb
