# Merged Mining RPC Adapter

A Python 3 service that acts as a bridge between P2Pool and standard cryptocurrency daemons
for merged mining support.

## Purpose

P2Pool's merged mining implementation expects certain RPC methods that standard daemons
may not provide (or provide differently). This adapter:

1. **Accepts** RPC calls from P2Pool on its configured port
2. **Translates** them to standard daemon RPC calls
3. **Builds AuxPOW proofs** when the parent chain finds a block
4. **Submits** blocks to the aux chain daemon with proper AuxPOW

## Architecture

```
┌─────────────┐   JSON-RPC   ┌──────────────┐   JSON-RPC   ┌─────────────┐
│   P2Pool    │◀────────────▶│  MM Adapter  │◀────────────▶│  Dogecoin   │
│  (PyPy 2.7) │  Port 44555  │ (Python 3)   │  Port 22555  │  (Standard) │
└─────────────┘              └──────────────┘              └─────────────┘
```

## Requirements

- Python 3.10+
- aiohttp
- Standard Dogecoin (or compatible) daemon with `getauxblock` support

## Installation

```bash
cd mm-adapter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy and edit the config file:

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings
```

## Running

```bash
# Activate venv if not already
source venv/bin/activate

# Run the adapter
python3 adapter.py --config config.yaml
```

Or with Docker:

```bash
docker build -t mm-adapter .
docker run -p 44555:44555 -v $(pwd)/config.yaml:/app/config.yaml mm-adapter
```

## P2Pool Configuration

Point P2Pool's merged mining settings to this adapter:

```bash
python run_p2pool.py \
    --net litecoin \
    ... \
    --merged-coind-address 127.0.0.1 \
    --merged-coind-rpc-port 44555 \
    --merged-coind-rpc-user adapter \
    --merged-coind-rpc-password adapterpass \
    ...
```

## Supported Aux Chains

- Dogecoin (Scrypt, chain_id=98)
- More coming...

## How It Works

### 1. Work Request (P2Pool → Adapter → Dogecoin)

```
P2Pool calls: getblocktemplate()
Adapter calls: getauxblock() on Dogecoin
Adapter returns: Modified template with aux chain data
```

### 2. Block Submission (P2Pool → Adapter → Dogecoin)

```
P2Pool calls: submitauxblock(aux_hash, auxpow_hex)
Adapter calls: getauxblock(aux_hash, auxpow_hex) on Dogecoin
Adapter returns: Success/failure
```

## Development

```bash
# Run tests
pytest tests/

# Run with debug logging
python3 adapter.py --config config.yaml --debug
```

## License

Same as P2Pool - GNU GPL v3
