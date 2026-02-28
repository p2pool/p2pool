#!/usr/bin/env python3
"""
Merged Mining RPC Adapter

This adapter enables MULTI-ADDRESS merged mining using ONLY standard daemon RPCs.
It uses getblocktemplate (not createauxblock) so P2Pool can build its own coinbase:

1. Returns raw block template data to P2Pool (not pre-built blocks)
2. P2Pool builds custom coinbase with PPLNS shareholder addresses
3. P2Pool calculates merkle root and block hash itself
4. P2Pool submits complete block via submitblock

Flow:
=====
P2Pool                          Adapter                         Standard Daemon
  |                                |                                   |
  | getblocktemplate(auxpow)       |                                   |
  |------------------------------->| getblocktemplate()                |
  |                                |---------------------------------->|
  |                                |<-- {prev_hash, bits, txs, value}  |
  |<-- {auxpow: {chainid, target}, |                                   |
  |     coinbasevalue, txs, bits}  |                                   |
  |                                |                                   |
  | [P2Pool builds coinbase with   |                                   |
  |  multiple miner addresses]     |                                   |
  | [P2Pool calculates merkle_root]|                                   |
  | [P2Pool builds block header]   |                                   |
  | [P2Pool calculates block hash] |                                   |
  | [Hash goes into parent chain]  |                                   |
  |                                |                                   |
  | submitblock(complete_block_hex)|                                   |
  |------------------------------->| submitblock(block_hex)            |
  |                                |---------------------------------->|
  |                                |<-- result                         |
  |<-- result                      |                                   |

Key insight: We DON'T use createauxblock. We return getblocktemplate data
with an auxpow marker, and P2Pool handles all coinbase/merkle/hash building.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import struct
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

import aiohttp
from aiohttp import web
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('mm-adapter')

# Suppress noisy aiohttp access logs (every HTTP request)
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)


# Chain configurations
CHAIN_CONFIGS = {
    'dogecoin': {
        'name': 'Dogecoin',
        'symbol': 'DOGE',
        'chainid': 98,  # 0x62 - Dogecoin's AuxPOW chain ID
        'default_port': 22555,
        'testnet_port': 44555,
    },
    'dogecoin_testnet': {
        'name': 'Dogecoin Testnet',
        'symbol': 'tDOGE',
        'chainid': 98,
        'default_port': 44555,
        'testnet_port': 44555,
    },
    'bellscoin': {
        'name': 'Bellscoin',
        'symbol': 'BELLS',
        'chainid': 0,  # TODO: Get actual chainid
        'default_port': 19918,
        'testnet_port': 19919,
    },
    'junkcoin': {
        'name': 'Junkcoin',
        'symbol': 'JKC',
        'chainid': 0,  # TODO: Get actual chainid  
        'default_port': 9771,
        'testnet_port': 19771,
    },
}


class JsonRpcError(Exception):
    """JSON-RPC error from upstream daemon."""
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC Error {code}: {message}")


@dataclass
class BlockTemplate:
    """Cached block template from upstream daemon."""
    version: int
    previous_block_hash: str
    transactions: List[Dict]
    coinbase_value: int
    target: str
    bits: str
    cur_time: int
    min_time: int
    height: int
    mutable: List[str]
    rules: List[str]
    # Metadata
    fetched_at: float = field(default_factory=time.time)
    chainid: int = 0


class UpstreamRPC:
    """JSON-RPC client for the upstream daemon."""
    
    def __init__(self, url: str, user: str, password: str, timeout: int = 30):
        self.url = url
        self.auth = aiohttp.BasicAuth(user, password)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._id = 0
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create persistent HTTP session (connection pooling)."""
        if self._session is None or self._session.closed:
            # keepalive_timeout=60 keeps TCP connection alive between calls
            conn = aiohttp.TCPConnector(limit=4, keepalive_timeout=60)
            self._session = aiohttp.ClientSession(
                auth=self.auth, timeout=self.timeout, connector=conn)
        return self._session
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def call(self, method: str, *params) -> Any:
        """Make a JSON-RPC call to the upstream daemon."""
        self._id += 1
        payload = {
            "jsonrpc": "1.0",
            "id": self._id,
            "method": method,
            "params": list(params)
        }
        
        log.debug(f"RPC -> {method}({params[:2]}{'...' if len(params) > 2 else ''})")
        
        session = await self._get_session()
        async with session.post(self.url, json=payload) as resp:
            if resp.status == 401:
                raise JsonRpcError(-1, "Authentication failed")
            
            result = await resp.json()
            
            if result.get('error'):
                err = result['error']
                raise JsonRpcError(
                    err.get('code', -1),
                    err.get('message', 'Unknown error'),
                    err.get('data')
                )
            
            res = result.get('result')
            log.debug(f"RPC <- {method}: {str(res)[:80]}{'...' if res and len(str(res)) > 80 else ''}")
            return res
    
    async def call_batch(self, calls: List[Tuple[str, List]]) -> List[Any]:
        """Make multiple JSON-RPC calls in a batch."""
        batch = []
        for method, params in calls:
            self._id += 1
            batch.append({
                "jsonrpc": "1.0",
                "id": self._id,
                "method": method,
                "params": params
            })
        
        session = await self._get_session()
        async with session.post(self.url, json=batch) as resp:
            if resp.status == 401:
                raise JsonRpcError(-1, "Authentication failed")
            
            results = await resp.json()
            
            outputs = []
            for result in results:
                if result.get('error'):
                    err = result['error']
                    outputs.append(JsonRpcError(
                        err.get('code', -1),
                        err.get('message', 'Unknown error')
                    ))
                else:
                    outputs.append(result.get('result'))
            
            return outputs


class MultiAddressMergedMiningAdapter:
    """
    Sophisticated merged mining adapter supporting multiple payout addresses.
    
    This adapter does NOT use createauxblock. Instead, it:
    1. Returns raw block template data via getblocktemplate
    2. P2Pool builds custom coinbase with multiple addresses
    3. P2Pool calculates merkle root and block hash
    4. P2Pool submits complete block via submitblock
    
    The approach:
    - getblocktemplate → P2Pool builds coinbase → submitblock
    """
    
    # Default coinbase text for OP_RETURN
    DEFAULT_COINBASE_TEXT = "technocore"
    
    def __init__(self, config: Dict):
        self.config = config
        upstream = config['upstream']
        self.rpc = UpstreamRPC(
            f"http://{upstream['host']}:{upstream['port']}/",
            upstream['rpc_user'],
            upstream['rpc_password'],
            upstream.get('timeout', 30)
        )
        
        # Chain configuration
        chain_config = config.get('chain', {})
        self.chain_name = chain_config.get('name', 'unknown')
        self.chainid = chain_config.get('chain_id', 0)
        
        # Coinbase text for OP_RETURN (default: "technocore")
        self.coinbase_text = config.get('coinbase_text', self.DEFAULT_COINBASE_TEXT)
        
        # Auto-detect chainid if not configured
        self._chainid_detected = False
        
        # Template cache
        self._current_template: Optional[BlockTemplate] = None
        self._template_lock = asyncio.Lock()
        
        # --- Cached state (updated by background poller) ---
        self.cached_tip_hash: Optional[str] = None       # getbestblockhash result
        self.cached_response_time: float = 0             # When last built
        
        # Background poller settings
        poll_cfg = config.get('polling', {})
        self.poll_interval: float = poll_cfg.get('interval', 1.0)  # seconds
        self._poller_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Stats
        self.stats = {
            'templates_served': 0,
            'blocks_submitted': 0,
            'blocks_accepted': 0,
            'blocks_rejected': 0,
            'last_template_time': None,
            'last_submit_time': None,
            'polls': 0,
            'cache_hits': 0,
            'cache_misses': 0,
        }
    
    # ---- Background poller ----
    async def start_poller(self):
        """Start the background template poller."""
        self._running = True
        self._poller_task = asyncio.ensure_future(self._poll_loop())
        log.info(f"Background poller started (interval={self.poll_interval}s)")
    
    async def stop_poller(self):
        """Stop the background poller."""
        self._running = False
        if self._poller_task:
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                pass
    
    async def _poll_loop(self):
        """Background loop: poll daemon for new work every poll_interval seconds."""
        while self._running:
            try:
                await self._refresh_template()
                self.stats['polls'] += 1
            except Exception as e:
                log.error(f"Poller error: {e}")
            await asyncio.sleep(self.poll_interval)
    
    async def _refresh_template(self):
        """Fetch fresh template and update cache.
        
        Optimization: first check getbestblockhash. If the tip hasn't
        changed and cache is fresh (<5s), skip the expensive getblocktemplate.
        Full refresh is forced every 5s for mempool freshness.
        """
        FULL_REFRESH_INTERVAL = 5.0

        try:
            tip_hash = await self.rpc.call('getbestblockhash')
        except Exception:
            tip_hash = None

        now = time.time()
        tip_changed = (tip_hash != self.cached_tip_hash)
        needs_full = (tip_changed
                      or self._current_template is None
                      or now - self.cached_response_time >= FULL_REFRESH_INTERVAL)

        if not needs_full:
            return  # Tip unchanged, cache fresh enough — skip heavy work

        # Fetch new template
        try:
            try:
                template_raw = await self.rpc.call('getblocktemplate', {'rules': ['segwit']})
            except JsonRpcError as e:
                if 'segwit' in str(e.message).lower():
                    template_raw = await self.rpc.call('getblocktemplate')
                else:
                    raise

            async with self._template_lock:
                self._current_template = BlockTemplate(
                    version=template_raw['version'],
                    previous_block_hash=template_raw['previousblockhash'],
                    transactions=template_raw.get('transactions', []),
                    coinbase_value=template_raw.get('coinbasevalue', 0),
                    target=template_raw.get('target', ''),
                    bits=template_raw['bits'],
                    cur_time=template_raw['curtime'],
                    min_time=template_raw.get('mintime', template_raw['curtime']),
                    height=template_raw.get('height', 0),
                    mutable=template_raw.get('mutable', ['time', 'transactions', 'prevblock']),
                    rules=template_raw.get('rules', []),
                    chainid=self.chainid,
                )
                self.cached_tip_hash = tip_hash
                self.cached_response_time = now
                self.stats['last_template_time'] = now

            if tip_changed:
                log.info(f"[POLLER] New tip: {tip_hash[:16]}... height={self._current_template.height}")
            else:
                log.debug(f"[POLLER] Refreshed template (mempool update)")

        except Exception as e:
            log.error(f"[POLLER] Template fetch failed: {e}")
    
    async def initialize(self):
        """Initialize adapter - detect chain info."""
        try:
            # Get blockchain info to detect chain
            info = await self.rpc.call('getblockchaininfo')
            chain = info.get('chain', 'unknown')
            
            log.info(f"Connected to upstream daemon: chain={chain}, blocks={info.get('blocks')}")
            
            # Auto-detect chainid from known chains
            if not self.chainid:
                for cfg_name, cfg in CHAIN_CONFIGS.items():
                    if cfg_name.startswith(chain) or chain in cfg_name:
                        self.chainid = cfg['chainid']
                        self.chain_name = cfg['name']
                        log.info(f"Auto-detected chain: {self.chain_name} (chainid={self.chainid})")
                        break
            
            if not self.chainid:
                # Try to get from getauxblock if available
                try:
                    auxblock = await self.rpc.call('getauxblock')
                    self.chainid = auxblock.get('chainid', 0)
                    log.info(f"Got chainid from getauxblock: {self.chainid}")
                except:
                    pass
            
            if not self.chainid:
                log.warning("Could not detect chainid - using 0")
                
        except Exception as e:
            log.error(f"Failed to initialize: {e}")
            raise
    
    async def get_block_template(self) -> BlockTemplate:
        """Return cached block template (kept fresh by background poller).
        
        Falls back to synchronous fetch if poller hasn't populated cache yet.
        """
        async with self._template_lock:
            if self._current_template is not None:
                self.stats['cache_hits'] += 1
                return self._current_template
        
        # Cache miss — first call before poller has run
        self.stats['cache_misses'] += 1
        log.debug("Template cache miss -- fetching synchronously")
        await self._refresh_template()
        
        async with self._template_lock:
            if self._current_template is None:
                raise JsonRpcError(-1, "Failed to fetch block template")
            return self._current_template
    
    async def handle_getblocktemplate(self, params: List) -> Dict:
        """
        Handle getblocktemplate call from P2Pool.
        
        When P2Pool requests auxpow capabilities, we return a template that
        P2Pool can use to build its own coinbase with multiple addresses.
        
        Unlike createauxblock, we don't return a pre-computed hash.
        P2Pool will:
        1. Build coinbase with PPLNS shareholder addresses
        2. Calculate merkle root from [coinbase, ...transactions]
        3. Build block header with that merkle root
        4. Hash the header to get the block hash
        5. Include that hash in parent chain (Litecoin) coinbase
        
        Coinbase text can be overridden per-request via params or uses config default.
        """
        # Check if this is an auxpow request
        capabilities = []
        coinbase_text_override = None
        if params and isinstance(params[0], dict):
            capabilities = params[0].get('capabilities', [])
            # Allow caller to override coinbase text
            coinbase_text_override = params[0].get('coinbase_text')
        
        if 'auxpow' not in capabilities:
            # Not a merged mining request - pass through
            return await self.rpc.call('getblocktemplate', *params)
        
        # Determine coinbase text: request override > config > default
        coinbase_text = coinbase_text_override or self.coinbase_text
        
        log.debug(f"Handling merged mining getblocktemplate (multiaddress, coinbase_text='{coinbase_text}')")
        
        # Get fresh template
        template = await self.get_block_template()
        
        self.stats['templates_served'] += 1
        
        # Build response in format P2Pool expects for multiaddress merged mining
        # Key: NO 'hash' in auxpow - P2Pool calculates this from custom coinbase
        response = {
            'version': template.version,
            'previousblockhash': template.previous_block_hash,
            'transactions': template.transactions,
            'coinbasevalue': template.coinbase_value,
            'target': template.target,
            'mintime': template.min_time,
            'curtime': template.cur_time,
            'mutable': template.mutable,
            'height': template.height,
            'bits': template.bits,
            'rules': template.rules,
            
            # The auxpow object tells P2Pool this is auxpow-capable
            # but without a pre-computed hash - P2Pool builds its own
            'auxpow': {
                'chainid': self.chainid,
                'target': template.target,
                # NO 'hash' here - that's the key difference!
                # P2Pool will build coinbase and calculate hash itself
                'coinbasevalue': template.coinbase_value,
                # Coinbase text for OP_RETURN in merged block
                'coinbase_text': coinbase_text,
            }
        }
        
        log.debug(f"Serving template: height={template.height}, "
                 f"coinbasevalue={template.coinbase_value}, "
                 f"txs={len(template.transactions)}, chainid={self.chainid}")
        
        return response
    
    async def handle_submitblock(self, params: List) -> Any:
        """
        Handle submitblock call from P2Pool.
        
        P2Pool builds the complete merged block including:
        - Block header (with custom merkle root from PPLNS coinbase)
        - AuxPOW proof (linking to parent chain)
        - Coinbase transaction (with multiple payout addresses)
        - Other transactions
        
        We just pass this through to the daemon.
        """
        if not params:
            raise JsonRpcError(-1, "submitblock requires block data")
        
        block_hex = params[0]
        
        log.info(f"Submitting block: {len(block_hex)} hex chars")
        self.stats['blocks_submitted'] += 1
        self.stats['last_submit_time'] = time.time()
        
        try:
            result = await self.rpc.call('submitblock', block_hex)
            
            # submitblock returns null on success, error message on failure
            if result is None:
                log.info("Block ACCEPTED by daemon!")
                self.stats['blocks_accepted'] += 1
                # Trigger immediate template refresh after block acceptance
                asyncio.ensure_future(self._refresh_template())
                return None
            else:
                log.warning(f"Block rejected: {result}")
                self.stats['blocks_rejected'] += 1
                return result
                
        except JsonRpcError as e:
            log.error(f"submitblock RPC error: {e}")
            self.stats['blocks_rejected'] += 1
            raise
    
    async def handle_submitauxblock(self, params: List) -> Any:
        """
        Handle submitauxblock for backward compatibility.
        
        This is for the simple single-address mode. In multiaddress mode,
        P2Pool uses submitblock instead.
        """
        if len(params) < 2:
            raise JsonRpcError(-1, "submitauxblock requires hash and auxpow")
        
        aux_hash = params[0]
        auxpow_hex = params[1]
        
        log.info(f"submitauxblock (legacy): hash={aux_hash[:16]}...")
        
        # Pass through to daemon
        return await self.rpc.call('submitauxblock', aux_hash, auxpow_hex)
    
    async def handle_getauxblock(self, params: List) -> Any:
        """
        Handle getauxblock for backward compatibility.
        
        This provides single-address fallback mode.
        """
        if len(params) == 0:
            # Work request - wallet mode
            return await self.rpc.call('getauxblock')
        elif len(params) == 1:
            # createauxblock equivalent
            return await self.rpc.call('createauxblock', params[0])
        else:
            # Submission
            return await self.rpc.call('getauxblock', params[0], params[1])
    
    async def handle_createauxblock(self, params: List) -> Any:
        """Pass through createauxblock for single-address fallback."""
        if not params:
            raise JsonRpcError(-1, "createauxblock requires address")
        return await self.rpc.call('createauxblock', params[0])
    
    async def handle_rpc_request(self, method: str, params: List) -> Any:
        """Route RPC requests to appropriate handlers."""
        
        log.debug(f"Handling RPC: {method}")
        
        # Merged mining methods
        if method == 'getbestblockhash':
            # Return cached tip hash instantly (zero upstream cost)
            if self.cached_tip_hash:
                self.stats['cache_hits'] += 1
                return self.cached_tip_hash
            return await self.rpc.call('getbestblockhash')
        
        elif method == 'getblocktemplate':
            return await self.handle_getblocktemplate(params)
        
        elif method == 'submitblock':
            return await self.handle_submitblock(params)
        
        elif method == 'submitauxblock':
            return await self.handle_submitauxblock(params)
        
        elif method == 'getauxblock':
            return await self.handle_getauxblock(params)
        
        elif method == 'createauxblock':
            return await self.handle_createauxblock(params)
        
        # Info methods - useful for debugging
        elif method == 'getblockchaininfo':
            return await self.rpc.call('getblockchaininfo')
        
        elif method == 'getnetworkinfo':
            return await self.rpc.call('getnetworkinfo')
        
        elif method == 'getmininginfo':
            return await self.rpc.call('getmininginfo')
        
        elif method == 'getblock':
            return await self.rpc.call('getblock', *params)
        
        elif method == 'getblockhash':
            return await self.rpc.call('getblockhash', *params)
        
        # Adapter stats (custom method)
        elif method == 'getadapterstats':
            return {
                'chain': self.chain_name,
                'chainid': self.chainid,
                'coinbase_text': self.coinbase_text,
                'stats': self.stats,
                'mode': 'multiaddress',
            }
        
        else:
            # Pass through unknown methods
            log.debug(f"Passing through: {method}")
            return await self.rpc.call(method, *params)
    
    async def close(self):
        """Cleanup resources."""
        await self.stop_poller()
        await self.rpc.close()


class RPCServer:
    """JSON-RPC server that accepts connections from P2Pool."""
    
    def __init__(self, adapter: MultiAddressMergedMiningAdapter, config: Dict):
        self.adapter = adapter
        self.config = config
        self.server_config = config['server']
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
    
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
        
        # Handle batch requests
        if isinstance(body, list):
            responses = []
            for req in body:
                resp = await self._handle_single_request(req)
                responses.append(resp)
            return web.json_response(responses)
        
        return web.json_response(await self._handle_single_request(body))
    
    async def _handle_single_request(self, body: Dict) -> Dict:
        """Handle a single JSON-RPC request."""
        request_id = body.get('id')
        method = body.get('method', '')
        params = body.get('params', [])
        
        start_time = time.time()
        
        try:
            result = await self.adapter.handle_rpc_request(method, params)
            elapsed = (time.time() - start_time) * 1000
            
            if method not in ('getblocktemplate',):  # Don't spam for frequent calls
                log.debug(f"RPC {method}: OK ({elapsed:.1f}ms)")
            
            return {
                'jsonrpc': '1.0',
                'id': request_id,
                'result': result,
                'error': None
            }
        except JsonRpcError as e:
            elapsed = (time.time() - start_time) * 1000
            log.warning(f"RPC {method}: Error {e.code} ({elapsed:.1f}ms)")
            return {
                'jsonrpc': '1.0',
                'id': request_id,
                'result': None,
                'error': {'code': e.code, 'message': e.message}
            }
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            log.exception(f"RPC {method}: Exception ({elapsed:.1f}ms)")
            return {
                'jsonrpc': '1.0',
                'id': request_id,
                'result': None,
                'error': {'code': -1, 'message': str(e)}
            }
    
    async def run(self):
        """Start the RPC server."""
        self._app = web.Application()
        self._app.router.add_post('/', self.handle_request)
        
        # Also handle GET for simple health check
        async def health_check(request):
            return web.json_response({
                'status': 'ok',
                'mode': 'multiaddress',
                'chain': self.adapter.chain_name,
                'chainid': self.adapter.chainid,
            })
        self._app.router.add_get('/', health_check)
        
        host = self.server_config['host']
        port = self.server_config['port']
        
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        
        log.info(f"")
        log.info(f"{'=' * 60}")
        log.info(f"MM Adapter listening on {host}:{port}")
        log.info(f"Upstream daemon: {self.config['upstream']['host']}:{self.config['upstream']['port']}")
        log.info(f"Chain: {self.adapter.chain_name} (chainid={self.adapter.chainid})")
        log.info(f"{'=' * 60}")
        log.info(f"")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
    
    async def shutdown(self):
        """Graceful shutdown."""
        if self._runner:
            await self._runner.cleanup()
        await self.adapter.close()


def load_config(path: str) -> Dict:
    """Load configuration from YAML file."""
    with open(path, 'r') as f:
        return yaml.safe_load(f)


async def main():
    parser = argparse.ArgumentParser(
        description='Merged Mining RPC Adapter'
    )
    parser.add_argument('--config', '-c', default='config.yaml',
                        help='Config file path')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--log-file', '-l',
                        help='Log to file (overrides config logging.file)')
    parser.add_argument('--host', help='Override listen host')
    parser.add_argument('--port', '-p', type=int, help='Override listen port')
    parser.add_argument('--upstream', '-u', help='Override upstream URL (host:port)')
    args = parser.parse_args()
    
    # Load config
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        log.error(f"Config file not found: {args.config}")
        sys.exit(1)
    
    # Apply overrides
    if args.host:
        config['server']['host'] = args.host
    if args.port:
        config['server']['port'] = args.port
    if args.upstream:
        host, port = args.upstream.split(':')
        config['upstream']['host'] = host
        config['upstream']['port'] = int(port)
    
    # Set logging level and optional log file
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        log_level = config.get('logging', {}).get('level', 'INFO')
        logging.getLogger().setLevel(getattr(logging, log_level))
    
    # Add file handler if configured (CLI --log-file overrides config)
    log_file = args.log_file or config.get('logging', {}).get('file')
    if log_file:
        import os
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logging.getLogger().addHandler(file_handler)
        log.info(f"Logging to file: {log_file}")
    
    # Create and initialize adapter
    adapter = MultiAddressMergedMiningAdapter(config)
    
    try:
        await adapter.initialize()
    except Exception as e:
        log.error(f"Failed to initialize adapter: {e}")
        sys.exit(1)
    
    # Start background poller
    await adapter.start_poller()
    
    # Create and run server
    server = RPCServer(adapter, config)
    
    try:
        await server.run()
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        await server.shutdown()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
