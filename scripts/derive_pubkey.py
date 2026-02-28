#!/usr/bin/env python3
"""
Derive compressed public key from BIP39 mnemonic phrase.
Uses Trust Wallet's default BIP44 derivation path for Dash: m/44'/5'/0'/0/0

SAFE: Only prints the PUBLIC key. Never writes mnemonic/private key to disk.
Run: .venv/bin/python scripts/derive_pubkey.py
"""

import getpass
import hashlib
import sys

from bip_utils import (
    Bip39SeedGenerator,
    Bip44,
    Bip44Coins,
    Bip44Changes,
)

TARGET_PKH = "20cb5c22b1e4d5947e5c112c7696b51ad9af3c61"

def hash160(data):
    sha = hashlib.sha256(data).digest()
    return hashlib.new('ripemd160', sha).hexdigest()

def main():
    print("=" * 60)
    print("Derive compressed pubkey from BIP39 mnemonic")
    print("Target pubkey hash: %s" % TARGET_PKH)
    print("Target Dash address: YOUR_DASH_ADDRESS")
    print("Target LTC address:  LU66WRMeuxt45vwGh9bWopRsBaZ8owBAb6")
    print("=" * 60)
    print()
    
    # Secure input — won't echo to terminal
    mnemonic = getpass.getpass("Enter mnemonic phrase (hidden): ")
    
    # Generate seed
    seed = Bip39SeedGenerator(mnemonic).Generate()
    
    # Try multiple derivation paths (Trust Wallet uses BIP44)
    # Dash: m/44'/5'/0'/0/0
    # Litecoin: m/44'/2'/0'/0/0
    paths = [
        ("Dash BIP44 m/44'/5'/0'/0/0", Bip44Coins.DASH),
        ("Litecoin BIP44 m/44'/2'/0'/0/0", Bip44Coins.LITECOIN),
    ]
    
    found = False
    for label, coin in paths:
        try:
            bip44 = Bip44.FromSeed(seed, coin)
            account = bip44.Purpose().Coin().Account(0)
            chain = account.Change(Bip44Changes.CHAIN_EXT)
            # Try first 20 addresses
            for i in range(20):
                addr_key = chain.AddressIndex(i)
                pub_hex = addr_key.PublicKey().RawCompressed().ToHex()
                pkh = hash160(bytes.fromhex(pub_hex))
                
                if pkh == TARGET_PKH:
                    print()
                    print("MATCH FOUND!")
                    print("  Path: %s (index %d)" % (label, i))
                    print("  Compressed pubkey: %s" % pub_hex)
                    print("  Pubkey hash: %s" % pkh)
                    print("  Length: %d bytes" % (len(pub_hex) // 2))
                    found = True
                    break
                    
            if found:
                break
        except Exception as e:
            print("  %s: %s" % (label, e))
    
    if not found:
        print()
        print("No match found in first 20 addresses of standard paths.")
        print("Trying more indices and paths...")
        
        # Extended search
        for label, coin in paths:
            try:
                bip44 = Bip44.FromSeed(seed, coin)
                account = bip44.Purpose().Coin().Account(0)
                for change in [Bip44Changes.CHAIN_EXT, Bip44Changes.CHAIN_INT]:
                    chain = account.Change(change)
                    for i in range(100):
                        addr_key = chain.AddressIndex(i)
                        pub_hex = addr_key.PublicKey().RawCompressed().ToHex()
                        pkh = hash160(bytes.fromhex(pub_hex))
                        if pkh == TARGET_PKH:
                            change_name = "external" if change == Bip44Changes.CHAIN_EXT else "internal"
                            print("MATCH FOUND!")
                            print("  Path: %s/%s/index %d" % (label, change_name, i))
                            print("  Compressed pubkey: %s" % pub_hex)
                            print("  Pubkey hash: %s" % pkh)
                            found = True
                            break
                    if found:
                        break
            except Exception as e:
                pass
            if found:
                break
    
    if not found:
        print("Could not find matching pubkey. The mnemonic may use a different derivation path.")
    
    # Clear sensitive data
    mnemonic = "x" * len(mnemonic)
    seed = b'\x00' * 64
    del mnemonic, seed

if __name__ == "__main__":
    main()
