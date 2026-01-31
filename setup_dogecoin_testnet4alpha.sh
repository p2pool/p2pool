#!/bin/bash
# Setup Dogecoin Testnet4 - Custom P2Pool merged mining testnet
# Run this on the Dogecoin node VM (192.168.86.27)
#
# WHY THIS IS NEEDED:
# The official Dogecoin testnet has a critical difficulty adjustment bug
# that allows unlimited minimum difficulty blocks via timestamp manipulation.
# This causes ~3.3 blocks/second instead of 1 block/minute, making merged
# mining testing impossible due to stale work.
#
# See: DOGECOIN_TESTNET_BUG.md for full documentation
# Official fix: https://github.com/dogecoin/dogecoin/pull/3967
#
# When Dogecoin Core releases official testnet4alpha, migrate to that instead.

set -e

DOGE_DIR="$HOME/dogecoin-auxpow-gbt"
CHAINPARAMS="$DOGE_DIR/src/chainparams.cpp"
CHAINPARAMSBASE="$DOGE_DIR/src/chainparamsbase.cpp"
INIT_CPP="$DOGE_DIR/src/init.cpp"
UTIL_CPP="$DOGE_DIR/src/util.cpp"

echo "=== Setting up Dogecoin Testnet4 ==="
echo ""

# Backup original files
echo "Backing up original files..."
cp "$CHAINPARAMS" "$CHAINPARAMS.backup"
cp "$CHAINPARAMSBASE" "$CHAINPARAMSBASE.backup"
cp "$INIT_CPP" "$INIT_CPP.backup"
cp "$UTIL_CPP" "$UTIL_CPP.backup"

# 1. Add CTestNet4Params class to chainparams.cpp (after line 372)
echo "Adding CTestNet4Params to chainparams.cpp..."

# Create the testnet4alpha class code
cat > /tmp/testnet4alpha_class.cpp << 'ENDOFCLASS'

/**
 * Testnet4 - Custom P2Pool merged mining testnet
 * 
 * Key features:
 * - New genesis block (Jan 2026)
 * - AuxPoW enabled from block 0
 * - Digishield difficulty adjustment from block 0
 * - Proper 60-second block time target
 * - No seed nodes (isolated network)
 */
class CTestNet4Params : public CChainParams {
public:
    CTestNet4Params() {
        strNetworkID = "testnet4alpha";

        // Single consensus params - AuxPoW + Digishield from genesis
        consensus.nHeightEffective = 0;
        consensus.nSubsidyHalvingInterval = 100000;
        consensus.nMajorityEnforceBlockUpgrade = 51;
        consensus.nMajorityRejectBlockOutdated = 75;
        consensus.nMajorityWindow = 100;
        
        // No BIP34/65/66 enforcement on this testnet (start fresh)
        consensus.BIP34Height = 0;
        consensus.BIP34Hash = uint256();
        consensus.BIP65Height = 0;
        consensus.BIP66Height = 0;
        
        // Difficulty settings - proper Digishield from start
        consensus.powLimit = uint256S("0x00000fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff");
        consensus.nPowTargetTimespan = 60; // Digishield: 1 minute
        consensus.nPowTargetSpacing = 60;  // 1 minute blocks
        consensus.fDigishieldDifficultyCalculation = true;
        consensus.fSimplifiedRewards = true;
        consensus.nCoinbaseMaturity = 30;  // Lower maturity for testing
        consensus.fPowAllowMinDifficultyBlocks = false;  // NO min difficulty!
        consensus.fPowAllowDigishieldMinDifficultyBlocks = false;  // NO min difficulty!
        consensus.fPowNoRetargeting = false;  // Allow retargeting
        
        consensus.nRuleChangeActivationThreshold = 75; // 75%
        consensus.nMinerConfirmationWindow = 100;
        
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = 999999999999ULL;

        consensus.vDeployments[Consensus::DEPLOYMENT_CSV].bit = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_CSV].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_CSV].nTimeout = 999999999999ULL;

        consensus.vDeployments[Consensus::DEPLOYMENT_SEGWIT].bit = 1;
        consensus.vDeployments[Consensus::DEPLOYMENT_SEGWIT].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_SEGWIT].nTimeout = 0; // Disabled

        consensus.nMinimumChainWork = uint256S("0x00");
        consensus.defaultAssumeValid = uint256S("0x00");

        // AuxPoW parameters - enabled from block 0
        consensus.nAuxpowChainId = 0x0062; // 98 - Same as mainnet Dogecoin
        consensus.fStrictChainId = false;  // Allow non-strict for testing
        consensus.fAllowLegacyBlocks = true;  // Allow legacy blocks for genesis

        // No consensus tree needed - single params
        pConsensusRoot = &consensus;

        // New message start bytes (unique to testnet4alpha)
        pchMessageStart[0] = 0xfa;
        pchMessageStart[1] = 0xce;
        pchMessageStart[2] = 0xb0;
        pchMessageStart[3] = 0x04;  // "04" for testnet4alpha
        
        nDefaultPort = 44558;  // Different from testnet (44556) and mainnet (22556)
        nPruneAfterHeight = 1000;

        // NEW GENESIS BLOCK - January 26, 2026
        genesis = CreateGenesisBlock(1737907200, 385084, 0x1e0ffff0, 1, 88 * COIN);
        
        consensus.hashGenesisBlock = genesis.GetHash();
        
        // Genesis hash will be printed on first run
        // assert(consensus.hashGenesisBlock == uint256S("0x..."));
        assert(genesis.hashMerkleRoot == uint256S("0x5b2a3f53f605d62c53e62932dac6925e3d74afa5a4b459745c36d42d0ed26a69"));

        // No DNS seeds - this is an isolated testnet
        vSeeds.clear();

        // Same address prefixes as testnet
        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,113); // 0x71 - 'n' prefix
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,196); // 0xc4
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,241); // 0xf1
        base58Prefixes[EXT_PUBLIC_KEY] = boost::assign::list_of(0x04)(0x35)(0x87)(0xcf).convert_to_container<std::vector<unsigned char> >();
        base58Prefixes[EXT_SECRET_KEY] = boost::assign::list_of(0x04)(0x35)(0x83)(0x94).convert_to_container<std::vector<unsigned char> >();

        // No fixed seeds
        vFixedSeeds.clear();

        fMiningRequiresPeers = false;  // Allow solo mining
        fDefaultConsistencyChecks = false;
        fRequireStandard = false;
        fMineBlocksOnDemand = false;

        checkpointData = (CCheckpointData) {
            boost::assign::map_list_of
            ( 0, consensus.hashGenesisBlock)
        };

        chainTxData = ChainTxData{
            0,
            0,
            0
        };
    }
};
static CTestNet4Params testNet4Params;
ENDOFCLASS

# Insert after line 372
head -372 "$CHAINPARAMS" > /tmp/chainparams_new.cpp
cat /tmp/testnet4alpha_class.cpp >> /tmp/chainparams_new.cpp
tail -n +373 "$CHAINPARAMS" >> /tmp/chainparams_new.cpp
cp /tmp/chainparams_new.cpp "$CHAINPARAMS"

# 2. Add testnet4alpha to Params() function in chainparams.cpp
echo "Updating Params() function..."
sed -i 's/else if (chain == CBaseChainParams::TESTNET)/else if (chain == "testnet4alpha")\n        return testNet4Params;\n    else if (chain == CBaseChainParams::TESTNET)/' "$CHAINPARAMS"

# 3. Add CBaseTestNet4Params to chainparamsbase.cpp
echo "Adding CBaseTestNet4Params to chainparamsbase.cpp..."
sed -i '/class CBaseTestNetParams/i\
class CBaseTestNet4Params : public CBaseChainParams\
{\
public:\
    CBaseTestNet4Params()\
    {\
        nRPCPort = 44559;\
    }\
};\
' "$CHAINPARAMSBASE"

# Add static instance
sed -i 's/static CBaseTestNetParams testNetParams;/static CBaseTestNet4Params testNet4Params;\nstatic CBaseTestNetParams testNetParams;/' "$CHAINPARAMSBASE"

# Add to BaseParams() function
sed -i 's/else if (chain == CBaseChainParams::TESTNET)/else if (chain == "testnet4alpha")\n        return testNet4Params;\n    else if (chain == CBaseChainParams::TESTNET)/' "$CHAINPARAMSBASE"

# 4. Add -testnet4alpha option to init.cpp
echo "Adding -testnet4alpha to help message..."
sed -i 's/strUsage += HelpMessageOpt("-testnet"/strUsage += HelpMessageOpt("-testnet4alpha", _("Use testnet4alpha (P2Pool merged mining testnet)"));\n    strUsage += HelpMessageOpt("-testnet"/' "$INIT_CPP"

# 5. Add testnet4alpha detection to util.cpp
echo "Adding testnet4alpha detection to util.cpp..."
sed -i 's/bool fTestNet = GetBoolArg("-testnet", false);/bool fTestNet = GetBoolArg("-testnet", false);\n    if (GetBoolArg("-testnet4alpha", false))\n        return "testnet4alpha";/' "$UTIL_CPP"

echo ""
echo "=== Source modifications complete ==="
echo ""
echo "Now building Dogecoin with testnet4alpha support..."
echo ""

cd "$DOGE_DIR"

# Build
make -j$(nproc)

echo ""
echo "=== Build complete! ==="
echo ""
echo "To start testnet4alpha node:"
echo "  mkdir -p ~/.dogecoin-testnet4alpha"
echo "  ./src/dogecoind -testnet4alpha -datadir=~/.dogecoin-testnet4alpha -server -rpcuser=dogeuser -rpcpassword=dogepass123"
echo ""
echo "To connect from RPC:"
echo "  ./src/dogecoin-cli -testnet4alpha -rpcport=44559 -rpcuser=dogeuser -rpcpassword=dogepass123 getblockchaininfo"
echo ""
