#!/bin/bash
# Add Dogecoin Testnet4Alpha - P2Pool Merged Mining Private Testnet
#
# This script manually adds testnet4alpha support to Dogecoin Core.
# Run this on the Dogecoin node VM (192.168.86.27)
#
# WHY: Official testnet has block storm bug (PR #3967)
# See: DOGECOIN_TESTNET_BUG.md

set -e

DOGE_DIR="$HOME/dogecoin-auxpow-gbt"
CHAINPARAMS="$DOGE_DIR/src/chainparams.cpp"
CHAINPARAMSBASE="$DOGE_DIR/src/chainparamsbase.cpp"

echo "=== Adding Dogecoin Testnet4Alpha ==="
echo ""

# Check if already patched
if grep -q "testnet4alpha" "$CHAINPARAMS" 2>/dev/null; then
    echo "testnet4alpha already exists in chainparams.cpp"
    echo "Skipping patch, proceeding to build..."
else
    echo "Creating backup..."
    cp "$CHAINPARAMS" "$CHAINPARAMS.backup.$(date +%Y%m%d%H%M%S)"
    cp "$CHAINPARAMSBASE" "$CHAINPARAMSBASE.backup.$(date +%Y%m%d%H%M%S)"

    echo "Adding CTestNet4AlphaParams class..."
    
    # Create the testnet4alpha class
    cat > /tmp/testnet4alpha_class.cpp << 'ENDCLASS'

/**
 * Testnet4Alpha - P2Pool Merged Mining Private Testnet
 * 
 * Created: January 2026
 * Purpose: Work around official testnet block storm bug
 * See: https://github.com/dogecoin/dogecoin/pull/3967
 * 
 * Key fixes:
 * - fPowAllowMinDifficultyBlocks = false (prevents block storms)
 * - AuxPoW enabled from block 0
 * - Digishield difficulty from block 0
 * - Isolated network (no seed nodes)
 */
class CTestNet4AlphaParams : public CChainParams {
public:
    CTestNet4AlphaParams() {
        strNetworkID = "testnet4alpha";

        // Single consensus params - AuxPoW + Digishield from genesis
        consensus.nHeightEffective = 0;
        consensus.nSubsidyHalvingInterval = 100000;
        consensus.nMajorityEnforceBlockUpgrade = 51;
        consensus.nMajorityRejectBlockOutdated = 75;
        consensus.nMajorityWindow = 100;
        
        consensus.BIP34Height = 0;
        consensus.BIP34Hash = uint256();
        consensus.BIP65Height = 0;
        consensus.BIP66Height = 0;
        
        // CRITICAL: Proper difficulty - NO min difficulty blocks!
        consensus.powLimit = uint256S("0x00000fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff");
        consensus.nPowTargetTimespan = 60; // Digishield: 1 minute
        consensus.nPowTargetSpacing = 60;  // 1 minute blocks
        consensus.fDigishieldDifficultyCalculation = true;
        consensus.fSimplifiedRewards = true;
        consensus.nCoinbaseMaturity = 30;
        consensus.fPowAllowMinDifficultyBlocks = false;  // KEY FIX!
        consensus.fPowAllowDigishieldMinDifficultyBlocks = false;  // KEY FIX!
        consensus.fPowNoRetargeting = false;
        
        consensus.nRuleChangeActivationThreshold = 75;
        consensus.nMinerConfirmationWindow = 100;
        
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = 999999999999ULL;

        consensus.vDeployments[Consensus::DEPLOYMENT_CSV].bit = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_CSV].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_CSV].nTimeout = 999999999999ULL;

        consensus.vDeployments[Consensus::DEPLOYMENT_SEGWIT].bit = 1;
        consensus.vDeployments[Consensus::DEPLOYMENT_SEGWIT].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_SEGWIT].nTimeout = 999999999999ULL;

        // AuxPoW enabled from genesis
        consensus.nAuxpowChainId = 0x0062; // Same chain ID as mainnet
        consensus.fStrictChainId = false;  // Allow parent chains
        consensus.fAllowLegacyBlocks = false; // AuxPoW only
        
        consensus.nMinimumChainWork = uint256S("0x00");
        consensus.defaultAssumeValid = uint256S("0x00");

        // Use single consensus tree
        pConsensusRoot = &consensus;

        // Network magic - unique for testnet4alpha
        pchMessageStart[0] = 0xd4;
        pchMessageStart[1] = 0xd3;
        pchMessageStart[2] = 0xd2;
        pchMessageStart[3] = 0xd1;
        nDefaultPort = 44556;
        nPruneAfterHeight = 1000;

        // Genesis block - PLACEHOLDER (will be mined)
        // Using testnet genesis temporarily, will update after mining
        genesis = CreateGenesisBlock(1738886400, 0, 0x1e0ffff0, 1, 88 * COIN);
        
        // These will be updated after mining genesis
        consensus.hashGenesisBlock = uint256S("0x0000000000000000000000000000000000000000000000000000000000000000");

        vFixedSeeds.clear();
        vSeeds.clear();
        // No seeds - isolated network

        // Same address prefixes as testnet
        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,113); // 'n'
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,196); // '2'
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,241);
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        fMiningRequiresPeers = false;  // Solo mining OK
        fDefaultConsistencyChecks = false;
        fRequireStandard = false;
        fMineBlocksOnDemand = false;
    }
};
static CTestNet4AlphaParams testNet4AlphaParams;
ENDCLASS

    # Insert before regtest class (line 374 in original, after "static CTestNetParams testNetParams;")
    # Find the line number of "static CTestNetParams testNetParams;"
    LINE_NUM=$(grep -n "static CTestNetParams testNetParams;" "$CHAINPARAMS" | cut -d: -f1)
    if [ -z "$LINE_NUM" ]; then
        echo "ERROR: Could not find insertion point in chainparams.cpp"
        exit 1
    fi
    
    echo "Inserting testnet4alpha class after line $LINE_NUM..."
    
    # Split file and insert
    head -n "$LINE_NUM" "$CHAINPARAMS" > /tmp/chainparams_head.cpp
    tail -n +"$((LINE_NUM + 1))" "$CHAINPARAMS" > /tmp/chainparams_tail.cpp
    cat /tmp/chainparams_head.cpp /tmp/testnet4alpha_class.cpp /tmp/chainparams_tail.cpp > "$CHAINPARAMS"
    
    echo "Adding testnet4alpha to SelectParams()..."
    
    # Add to SelectParams function - find the right spot
    sed -i 's/else if (network == "regtest")/else if (network == "testnet4alpha") {\n            return testNet4AlphaParams;\n        } else if (network == "regtest")/' "$CHAINPARAMS"
    
    echo "Adding to chainparamsbase.cpp..."
    
    # Add to CBaseChainParams
    if ! grep -q "testnet4alpha" "$CHAINPARAMSBASE"; then
        sed -i 's/else if (chain == CBaseChainParams::REGTEST)/else if (chain == "testnet4alpha") {\n        return MakeUnique<CBaseChainParams>("testnet4alpha", 44555);\n    } else if (chain == CBaseChainParams::REGTEST)/' "$CHAINPARAMSBASE"
    fi
    
    echo "Patch applied successfully!"
fi

echo ""
echo "Building Dogecoin with testnet4alpha support..."
cd "$DOGE_DIR"

# Only run configure if Makefile doesn't exist
if [ ! -f Makefile ]; then
    echo "Running ./autogen.sh..."
    ./autogen.sh
    echo "Running ./configure..."
    ./configure --without-gui --without-miniupnpc --disable-tests --disable-bench
fi

echo "Building (this may take a while)..."
make -j$(nproc)

echo ""
echo "=== Build complete! ==="
echo ""
echo "Next steps:"
echo "1. Mine the genesis block (see mine_genesis.py)"
echo "2. Update genesis hash in chainparams.cpp"
echo "3. Rebuild"
echo "4. Start node with: ./src/dogecoind -testnet4alpha"
echo ""
echo "Or to start with current placeholder genesis (won't validate):"
echo "./src/dogecoind -testnet4alpha -listen=0"
