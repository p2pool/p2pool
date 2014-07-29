import unittest

from p2pool.bitcoin import data, networks
from p2pool.util import pack


class Test(unittest.TestCase):
    def test_header_hash(self):
        assert data.hash256(data.block_header_type.pack(dict(
            version=1,
            previous_block=0x000000000000038a2a86b72387f93c51298298a732079b3b686df3603d2f6282,
            merkle_root=0x37a43a3b812e4eb665975f46393b4360008824aab180f27d642de8c28073bc44,
            timestamp=1323752685,
            bits=data.FloatingInteger(437159528),
            nonce=3658685446,
        ))) == 0x000000000000003aaaf7638f9f9c0d0c60e8b0eb817dcdb55fd2b1964efc5175
    
    def test_header_hash_litecoin(self):
        assert networks.nets['litecoin'].POW_FUNC(data.block_header_type.pack(dict(
            version=1,
            previous_block=0xd928d3066613d1c9dd424d5810cdd21bfeef3c698977e81ec1640e1084950073,
            merkle_root=0x03f4b646b58a66594a182b02e425e7b3a93c8a52b600aa468f1bc5549f395f16,
            timestamp=1327807194,
            bits=data.FloatingInteger(0x1d01b56f),
            nonce=20736,
        ))) < 2**256//2**30
    
    def test_tx_hash(self):
        assert data.hash256(data.tx_type.pack(dict(
            version=1,
            tx_ins=[dict(
                previous_output=None,
                sequence=None,
                script='70736a0468860e1a0452389500522cfabe6d6d2b2f33cf8f6291b184f1b291d24d82229463fcec239afea0ee34b4bfc622f62401000000000000004d696e656420627920425443204775696c6420ac1eeeed88'.decode('hex'),
            )],
            tx_outs=[dict(
                value=5003880250,
                script=data.pubkey_hash_to_script2(pack.IntType(160).unpack('ca975b00a8c203b8692f5a18d92dc5c2d2ebc57b'.decode('hex'))),
            )],
            lock_time=0,
        ))) == 0xb53802b2333e828d6532059f46ecf6b313a42d79f97925e457fbbfda45367e5c
    
    def test_address_to_pubkey_hash(self):
        assert data.address_to_pubkey_hash('1KUCp7YP5FP8ViRxhfszSUJCTAajK6viGy', networks.nets['bitcoin']) == pack.IntType(160).unpack('ca975b00a8c203b8692f5a18d92dc5c2d2ebc57b'.decode('hex'))
    
    def test_merkle_hash(self):
        assert data.merkle_hash([
            0xb53802b2333e828d6532059f46ecf6b313a42d79f97925e457fbbfda45367e5c,
            0x326dfe222def9cf571af37a511ccda282d83bedcc01dabf8aa2340d342398cf0,
            0x5d2e0541c0f735bac85fa84bfd3367100a3907b939a0c13e558d28c6ffd1aea4,
            0x8443faf58aa0079760750afe7f08b759091118046fe42794d3aca2aa0ff69da2,
            0x4d8d1c65ede6c8eab843212e05c7b380acb82914eef7c7376a214a109dc91b9d,
            0x1d750bc0fa276f89db7e6ed16eb1cf26986795121f67c03712210143b0cb0125,
            0x5179349931d714d3102dfc004400f52ef1fed3b116280187ca85d1d638a80176,
            0xa8b3f6d2d566a9239c9ad9ae2ed5178dee4a11560a8dd1d9b608fd6bf8c1e75,
            0xab4d07cd97f9c0c4129cff332873a44efdcd33bdbfc7574fe094df1d379e772f,
            0xf54a7514b1de8b5d9c2a114d95fba1e694b6e3e4a771fda3f0333515477d685b,
            0x894e972d8a2fc6c486da33469b14137a7f89004ae07b95e63923a3032df32089,
            0x86cdde1704f53fce33ab2d4f5bc40c029782011866d0e07316d695c41e32b1a0,
            0xf7cf4eae5e497be8215778204a86f1db790d9c27fe6a5b9f745df5f3862f8a85,
            0x2e72f7ddf157d64f538ec72562a820e90150e8c54afc4d55e0d6e3dbd8ca50a,
            0x9f27471dfbc6ce3cbfcf1c8b25d44b8d1b9d89ea5255e9d6109e0f9fd662f75c,
            0x995f4c9f78c5b75a0c19f0a32387e9fa75adaa3d62fba041790e06e02ae9d86d,
            0xb11ec2ad2049aa32b4760d458ee9effddf7100d73c4752ea497e54e2c58ba727,
            0xa439f288fbc5a3b08e5ffd2c4e2d87c19ac2d5e4dfc19fabfa33c7416819e1ec,
            0x3aa33f886f1357b4bbe81784ec1cf05873b7c5930ab912ee684cc6e4f06e4c34,
            0xcab9a1213037922d94b6dcd9c567aa132f16360e213c202ee59f16dde3642ac7,
            0xa2d7a3d2715eb6b094946c6e3e46a88acfb37068546cabe40dbf6cd01a625640,
            0x3d02764f24816aaa441a8d472f58e0f8314a70d5b44f8a6f88cc8c7af373b24e,
            0xcc5adf077c969ebd78acebc3eb4416474aff61a828368113d27f72ad823214d0,
            0xf2d8049d1971f02575eb37d3a732d46927b6be59a18f1bd0c7f8ed123e8a58a,
            0x94ffe8d46a1accd797351894f1774995ed7df3982c9a5222765f44d9c3151dbb,
            0x82268fa74a878636261815d4b8b1b01298a8bffc87336c0d6f13ef6f0373f1f0,
            0x73f441f8763dd1869fe5c2e9d298b88dc62dc8c75af709fccb3622a4c69e2d55,
            0xeb78fc63d4ebcdd27ed618fd5025dc61de6575f39b2d98e3be3eb482b210c0a0,
            0x13375a426de15631af9afdf00c490e87cc5aab823c327b9856004d0b198d72db,
            0x67d76a64fa9b6c5d39fde87356282ef507b3dec1eead4b54e739c74e02e81db4,
        ]) == 0x37a43a3b812e4eb665975f46393b4360008824aab180f27d642de8c28073bc44
