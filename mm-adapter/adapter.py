#!/usr/bin/env python3
"""
Merged Mining RPC Adapter

Acts as a bridge between P2Pool and standard cryptocurrency daemons for merged mining.
Translates P2Pool's merged mining RPC calls to standard daemon RPC methods.

P2Pool tries these methods in order:
1. getblocktemplate({"capabilities": ["auxpow"]}) - Our modified daemon (multiaddress)
2. createauxblock(address) - Standard daemon with address
3. getauxblock() - Standard daemon with wallet

This adapter speaks method 1 to P2Pool but uses methods 2/3 to talk to standard daemons.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import struct
import sys
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from aiohttp import web
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('mm-adapter')


class JsonRpcError(Exception):
    """JSON-RPC error from upstream daemon."""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"JSON-RPC Error {code}: {message}")


class UpstreamRPC:
    """JSON-RPC client for the upstream daemon (e.g., Dogecoin)."""
    
    def __init__(self, url: str, user: str, password: str, timeout: int = 30):
        self.url = url
        self.auth = aiohttp.BasicAuth(user, password)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._id = 0
    
    async def call(self, method: str, *params) -> Any:
        """Make a JSON-RPC call to the upstream daemon."""
        self._id += 1
        payload = {
            "jsonrpc": "1.0",
            "id": self._id,
            "method": method,
            "params": list(params)
        }
        
        log.debug(f"RPC -> {method}({params})")
        
        async with aiohttp.ClientSession(auth=self.auth, timeout=self.timeout) as session:
            async with session.post(self.url, json=payload) as resp:
                if resp.status == 401:
                    raise JsonRpcError(-1, "Authentication failed")
                
                result = await resp.json()
                
                if result.get('error'):
                    err = result['error']
                    raise JsonRpcError(err.get('code', -1), err.get('message', 'Unknown error'))
                
                res = result.get('result')
                res_str = str(res)[:100] if res else ''
                log.debug(f"RPC <- {method}: {res_str}...")
                return res


class MergedMiningAdapter:
    """
    Translates P2Pool's merged mining RPC to standard daemon RPC.
    
    P2Pool expects:
    - getblocktemplate({"capabilities": ["auxpow"]}) → response with auxpow object
    
    Standard Dogecoin provides:
    - createauxblock(address) → {"hash": "...", "chainid": ..., "target": "..."}
    - getauxblock(hash, auxpow) → submits block
    """
    
    def __init__(self, config: Dict):
        self.config = config
        upstream = config['upstream']
        self.rpc = UpstreamRPC(
            f"http://{upstream['host']}:{upstream['port']}/",
            upstream['rpc_user'],
            upstream['rpc_password'],
            upstream.get('timeout', 30)
        )
        
        # Payout address for merged mining rewards
        self.payout_address = config.get('payout', {}).get('address')
        if not self.payout_address:
            log.warning("No payout address configured, will use wallet default")
        
        # Cache current aux work
        self.current_aux_work: Optional[Dict] = None
        self.aux_work_lock = asyncio.Lock()
        
        # Track pending aux blocks for submission
        self.pending_aux_blocks: Dict[str, Dict] = {}
    
    async def handle_getblocktemplate(self, params: List) -> Dict:
        """
        Handle getblocktemplate call from P2Pool.
        
        P2Pool calls: getblocktemplate({"capabilities": ["auxpow"]})
        We translate to: createauxblock(address) or getauxblock()
        """
        # Check if this is an auxpow request
        capabilities = []
        if params and isinstance(params[0], dict):
            capabilities = params[0].get('capabilities', [])
        
        if 'auxpow' not in capabilities:
            # Not a merged mining request, pass through
            return await self.rpc.call('getblocktemplate', *params)
        
        # This is a merged mining work request
        log.info("Handling merged mining getblocktemplate request")
        
        async with self.aux_work_lock:
            try:
                if self.payout_address:
                    # Use createauxblock with explicit address
                    auxblock = await self.rpc.call('createauxblock', self.payout_address)
                else:
                    # Use getauxblock (wallet-based)
                    auxblock = await self.rpc.call('getauxblock')
                
                log.info(f"Got aux block: hash={auxblock['hash'][:16]}... chainid={auxblock.get('chainid')}")
                
                # Store for later submission
                self.pending_aux_blocks[auxblock['hash']] = {
                    'auxblock': auxblock,
                    'use_submitauxblock': self.payout_address is not None
                }
                
                # Also get the full block template for transactions
                # (needed if P2Pool wants to build complete blocks)
                try:
                    template = await self.rpc.call('getblocktemplate', {"rules": ["segwit"]})
                except:
                    template = await self.rpc.call('getblocktemplate')
                
                # Build response in format P2Pool expects
                # This mimics what our modified Dogecoin returns
                response = {
                    'version': template.get('version', 1),
                    'previousblockhash': template.get('previousblockhash'),
                    'transactions': template.get('transactions', []),
                    'coinbasevalue': template.get('coinbasevalue', 0),
                    'target': auxblock.get('target', template.get('target')),
                    'mintime': template.get('mintime'),
                    'curtime': template.get('curtime'),
                    'mutable': template.get('mutable', ['time', 'transactions', 'prevblock']),
                    'height': template.get('height'),
                    'bits': template.get('bits'),
                    
                    # The key auxpow object P2Pool expects
                    'auxpow': {
                        'chainid': auxblock.get('chainid', self.config['chain']['chain_id']),
                        'target': auxblock.get('target'),
                        'hash': auxblock['hash'],
                        # These would be needed for full multiaddress support
                        # but for single-address mode they're not used
                        'coinbasevalue': template.get('coinbasevalue', 0),
                    }
                }
                
                self.current_aux_work = response
                return response
                
            except Exception as e:
                log.error(f"Error getting aux work: {e}")
                raise
    
    async def handle_submitauxblock(self, params: List) -> bool:
        """
        Handle submitauxblock call from P2Pool.
        
        P2Pool calls: submitauxblock(hash, auxpow_hex)
        We translate to: submitauxblock(hash, auxpow) or getauxblock(hash, auxpow)
        """
        if len(params) < 2:
            raise JsonRpcError(-1, "submitauxblock requires hash and auxpow parameters")
        
        aux_hash = params[0]
        auxpow_hex = params[1]
        
        log.info(f"Submitting aux block: hash={aux_hash[:16]}...")
        
        # Look up how we got this aux work
        pending = self.pending_aux_blocks.get(aux_hash)
        
        try:
            if pending and pending.get('use_submitauxblock'):
                # We used createauxblock, so use submitauxblock
                result = await self.rpc.call('submitauxblock', aux_hash, auxpow_hex)
            else:
                # We used getauxblock, so submit via getauxblock
                result = await self.rpc.call('getauxblock', aux_hash, auxpow_hex)
            
            log.info(f"Aux block submitted successfully: {aux_hash[:16]}...")
            
            # Clean up pending
            if aux_hash in self.pending_aux_blocks:
                del self.pending_aux_blocks[aux_hash]
            
            return result if result is not None else True
            
        except JsonRpcError as e:
            log.error(f"Aux block submission failed: {e}")
            raise
    
    async def handle_rpc_request(self, method: str, params: List) -> Any:
        """Route RPC requests to appropriate handlers."""
        
        log.debug(f"Handling RPC: {method}({params})")
        
        if method == 'getblocktemplate':
            return await self.handle_getblocktemplate(params)
        
        elif method == 'submitauxblock':
            return await self.handle_submitauxblock(params)
        
        elif method == 'getauxblock':
            # Could be work request or submission
            if len(params) == 0:
                # Work request - no address, use wallet
                auxblock = await self.rpc.call('getauxblock')
                self.pending_aux_blocks[auxblock['hash']] = {
                    'auxblock': auxblock,
                    'use_submitauxblock': False
                }
                return auxblock
            elif len(params) == 1:
                # createauxblock with address
                auxblock = await self.rpc.call('createauxblock', params[0])
                self.pending_aux_blocks[auxblock['hash']] = {
                    'auxblock': auxblock,
                    'use_submitauxblock': True
                }
                return auxblock
            else:
                # Submission: getauxblock(hash, auxpow)
                return await self.rpc.call('getauxblock', params[0], params[1])
        
        elif method == 'createauxblock':
            # Direct passthrough
            auxblock = await self.rpc.call('createauxblock', *params)
            self.pending_aux_blocks[auxblock['hash']] = {
                'auxblock': auxblock,
                'use_submitauxblock': True
            }
            return auxblock
        
        else:
            # Pass through any other methods
            return await self.rpc.call(method, *params)


class RPCServer:
    """JSON-RPC server that accepts connections from P2Pool."""
    
    def __init__(self, adapter: MergedMiningAdapter, config: Dict):
        self.adapter = adapter
        self.config = config
        self.server_config = config['server']
    
    def check_auth(self, request: web.Request) -> bool:
        """Verify Basic auth credentials."""
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Basic '):
            return False
        
        try:
            encoded = auth_header[6:]
            decoded = base64.b64decode(encoded).decode('utf-8')
            user, password = decoded.split(':', 1)
            return (user == self.server_config['rpc_user'] and 
                    password == self.server_config['rpc_password'])
        except:
            return False
    
    async def handle_request(self, request: web.Request) -> web.Response:
        """Handle incoming JSON-RPC request."""
        
        # Check authentication
        if not self.check_auth(request):
            return web.Response(status=401, text='Unauthorized')
        
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({
                'jsonrpc': '1.0',
                'id': None,
                'result': None,
                'error': {'code': -32700, 'message': 'Parse error'}
            })
        
        request_id = body.get('id')
        method = body.get('method', '')
        params = body.get('params', [])
        
        log.info(f"RPC request: {method}")
        
        try:
            result = await self.adapter.handle_rpc_request(method, params)
            return web.json_response({
                'jsonrpc': '1.0',
                'id': request_id,
                'result': result,
                'error': None
            })
        except JsonRpcError as e:
            return web.json_response({
                'jsonrpc': '1.0',
                'id': request_id,
                'result': None,
                'error': {'code': e.code, 'message': e.message}
            })
        except Exception as e:
            log.exception(f"Error handling {method}")
            return web.json_response({
                'jsonrpc': '1.0',
                'id': request_id,
                'result': None,
                'error': {'code': -1, 'message': str(e)}
            })
    
    async def run(self):
        """Start the RPC server."""
        app = web.Application()
        app.router.add_post('/', self.handle_request)
        
        host = self.server_config['host']
        port = self.server_config['port']
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(runner, host, port)
        await site.start()
        
        log.info(f"MM Adapter listening on {host}:{port}")
        log.info(f"Upstream daemon: {self.config['upstream']['host']}:{self.config['upstream']['port']}")
        
        # Keep running
        while True:
            await asyncio.sleep(3600)


def load_config(path: str) -> Dict:
    """Load configuration from YAML file."""
    with open(path, 'r') as f:
        return yaml.safe_load(f)


async def main():
    parser = argparse.ArgumentParser(description='Merged Mining RPC Adapter')
    parser.add_argument('--config', '-c', default='config.yaml', help='Config file path')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    config = load_config(args.config)
    
    # Override logging level from config
    log_level = config.get('logging', {}).get('level', 'INFO')
    logging.getLogger().setLevel(getattr(logging, log_level))
    
    adapter = MergedMiningAdapter(config)
    server = RPCServer(adapter, config)
    
    await server.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down...")
