# Copyright (c) 2018 Robert LeBlanc
# Copyright (c) 2017 Pieter Wuille
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import unittest
import mock

from p2pool.util import segwit_addr

class UnitTest(unittest.TestCase):

    def setUp(self):
        self.longMessage = True

    def test_bech32_polymod(self):
        data = [([3, 3, 0, 2, 3, 0, 14, 20, 15, 7, 13, 26, 0, 25, 18, 6, 11, 13,
                  8, 21, 4, 20, 3, 17, 2, 29, 3, 12, 29, 3, 4, 15, 24, 20, 6, 14,
                  30, 22, 12, 7, 9, 17, 11, 21], 1),
                ([3, 3, 3, 3, 0, 20, 12, 20, 3, 0, 30, 18, 12, 16, 17, 29, 3, 7,
                  15, 6, 6, 25, 6, 25, 13, 22, 3, 25, 23, 4, 29, 26, 9, 26, 18,
                  31, 0, 0, 27, 14, 13, 1, 0, 0, 0, 0, 0, 0], 477141089),
                ([3, 3, 0, 2, 3, 0, 14, 20, 15, 7, 13, 26, 0, 25, 18, 6, 11, 13,
                  8, 21, 4, 20, 3, 17, 2, 29, 3, 12,29, 3, 4, 15, 24, 20, 6, 14,
                  30, 22, 12, 7, 9, 17, 11, 21], 1),
                ([3, 3, 0, 2, 3, 0, 14, 20, 15, 7, 13, 26, 0, 25, 18, 6, 11, 13,
                  8, 21, 4, 20, 3, 17, 2, 29, 3, 12,29, 3, 4, 15, 24, 20, 6, 14,
                  30, 22, 0, 0, 0, 0, 0, 0], 410305908),
               ]
        for d, r in data:
            self.assertEqual(r, segwit_addr.bech32_polymod(d))

    def test_bech32_hrp_expand(self):
        data = [('bc', [3, 3, 0, 2, 3]),
                ('tltc', [3, 3, 3, 3, 0, 20, 12, 20, 3]),
               ]
        for d, r in data:
            self.assertEqual(r, segwit_addr.bech32_hrp_expand(d),
                             "HRP %s failed." % d)

    @mock.patch.object(segwit_addr, 'bech32_hrp_expand',
                       spec=segwit_addr.bech32_hrp_expand)
    @mock.patch.object(segwit_addr, 'bech32_polymod',
                       spec=segwit_addr.bech32_polymod)
    def test_bech_32_verify_checksum(self, mbp, mbhe):
        mbhe.return_value = ['foo']
        mbp.return_value = 0
        data = [('bc', [0, 14, 20, 15, 7, 13, 26, 0, 25, 18, 6, 11, 13, 8, 21,
                        4, 20, 3, 17, 2, 29, 3, 12, 29, 3, 4, 15, 24, 20, 6, 14,
                        30, 22, 12, 7, 9, 17, 11, 21]),
                ('ltc', [0, 30, 18, 12, 16, 17, 29, 3, 7, 15, 6, 6, 25, 6, 25,
                         13, 22, 3, 25, 23, 4, 29, 26, 9, 26, 18, 31, 0, 0, 27,
                         14, 13, 1, 14, 7, 1, 6, 3, 0]),
               ]
        self.assertFalse(segwit_addr.bech32_verify_checksum(*data[0]))
        mbhe.assert_called_once_with(data[0][0])
        mbp.assert_called_once_with(['foo'] + data[0][1])
        mbhe.reset_mock()
        mbp.reset_mock()
        mbhe.return_value = ['bar']
        mbp.return_value = 1
        self.assertTrue(segwit_addr.bech32_verify_checksum(*data[1]))
        mbhe.assert_called_once_with(data[1][0])
        mbp.assert_called_once_with(['bar'] + data[1][1])
        mbp.return_value = 2
        self.assertFalse(segwit_addr.bech32_verify_checksum(*data[1]))

    @mock.patch.object(segwit_addr, 'bech32_hrp_expand',
                       spec=segwit_addr.bech32_hrp_expand)
    @mock.patch.object(segwit_addr, 'bech32_polymod',
                       spec=segwit_addr.bech32_polymod)
    def test_bech32_create_checksum(self, mbp, mbhe):
        mbhe.return_value = ['foo']
        data = [('bc', 0, [0, 0, 0, 0, 0, 1]),
                ('tb', 1, [0, 0, 0, 0, 0, 0]),
                ('ltc', 410305908, [12, 7, 9, 17, 11, 21]),
                ('tltc', 477141089, [14, 7, 1, 6, 3, 0]),
               ]
        for h, d, r in data:
            mbhe.reset_mock()
            mbp.reset_mock()
            mbp.return_value = d
            self.assertListEqual(r, segwit_addr.bech32_create_checksum(h, ['bar']))
            mbhe.assert_called_once_with(h)
            mbp.assert_called_once_with(['foo'] + ['bar'] + [0] * 6)

    @mock.patch.object(segwit_addr, 'bech32_create_checksum',
                       spec=segwit_addr.bech32_create_checksum)
    def test_bech32_encode(self, mbcc):
        data = [('bc', [0, 14, 20, 15, 7, 13, 26, 0, 25, 18, 6, 11, 13, 8, 21,
                        4, 20, 3, 17, 2, 29, 3, 12, 29, 3, 4, 15, 24, 20, 6, 14,
                        30, 22],
                 [12, 7, 9, 17, 11, 21],
                 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4'),
                ('tltc', [0, 30, 18, 12, 16, 17, 29, 3, 7, 15, 6, 6, 25, 6, 25,
                          13, 22, 3, 25, 23, 4, 29, 26, 9, 26, 18, 31, 0, 0, 27,
                          14, 13, 1],
                 [14, 7, 1, 6, 3, 0],
                 'tltc1q7jvs3ar80xxexedkrehya6f6jlqqmwdpw8pxrq'),
               ]
        for h, d, c, r in data:
            mbcc.reset_mock()
            mbcc.return_value = c
            self.assertEqual(r, segwit_addr.bech32_encode(h, d))
            mbcc.assert_called_once_with(h, d)

    @mock.patch.object(segwit_addr, 'bech32_verify_checksum',
                       spec=segwit_addr.bech32_verify_checksum)
    def test_bech32_decode(self, mvc):
        # Test non-numeric and non-alpha range
        for i in range(33):
            self.assertTupleEqual((None, None), segwit_addr.bech32_decode(chr(i)))
        for i in range(127, 256):
            self.assertTupleEqual((None, None), segwit_addr.bech32_decode(chr(i)))
        # Test mixed case
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode('abcDef'))
        # Test missing HRP
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode('abcdef'))
        # Test address too short
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode('bc1ab'))
        # Test address too long
        addr = 'bc1acdefghjklmnpqrstuvwxyz234567890acdefghjklmnpqrstuvwxyz234567890acdefghjklmnpqrstuvwxyz2'
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode(addr))
        # Test illegal characters
        addr = 'bc1bcdefghjklm'
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode(addr))
        addr = 'bc1acdefghijklm'
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode(addr))
        addr = 'bc1acdefghijklm1'
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode(addr))
        # Check that bech32_verify_checksum hasn't been called.
        self.assertEqual(0, mvc.call_count)
        # Test that the checksum failed
        mvc.return_value = 0
        addr = 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4'
        data = [0, 14, 20, 15, 7, 13, 26, 0, 25, 18, 6, 11, 13, 8, 21, 4, 20, 3,
                17, 2, 29, 3, 12, 29, 3, 4, 15, 24, 20, 6, 14, 30, 22, 12, 7, 9,
                17, 11, 21]
        self.assertTupleEqual((None, None), segwit_addr.bech32_decode(addr))
        mvc.assert_called_once_with('bc', data)
        mvc.return_value = 1
        self.assertTupleEqual(('bc', data[:-6]), segwit_addr.bech32_decode(addr))

    @mock.patch.object(segwit_addr, 'bech32_decode',
                       spec=segwit_addr.bech32_decode)
    @mock.patch.object(segwit_addr, 'convertbits', spec=segwit_addr.convertbits)
    def test_decode(self, mcb, mbd):
        self.longMessage = True
        data = [0, 1, 2, 3, 4, 5]
        mbd.return_value = ('bc', data)
        addr = 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4'
        # Test wrong hrp
        self.assertTupleEqual((None, None), segwit_addr.decode('tltc', addr))
        self.assertEqual(0, mcb.call_count)
        mbd.assert_called_once_with(addr)
        # Test bad convertbits
        mcb.return_value = None
        self.assertTupleEqual((None, None), segwit_addr.decode('bc', addr))
        mcb.assert_called_once_with(data[1:], 5, 8, False)
        mcb.return_value = [0]
        self.assertTupleEqual((None, None), segwit_addr.decode('bc', addr))
        mcb.return_value = [0] * 41
        self.assertTupleEqual((None, None), segwit_addr.decode('bc', addr))
        # Test bad version
        mcb.return_value = [17] + [0] * 20
        self.assertTupleEqual((None, None), segwit_addr.decode('bc', addr))
        # Version 0: Test bad lengths and correct returns
        ret = []
        for i in range (1, 42):
            ret.append(i)
            mcb.return_value = ret
            if i == 20 or i == 32:
                self.assertTupleEqual((0, ret),
                        segwit_addr.decode('bc', addr),
                        "Failed with length %d" % i)
            else:
                self.assertTupleEqual((None, None),
                        segwit_addr.decode('bc', addr),
                        "Failed with length %d" % i)

    @mock.patch.object(segwit_addr, 'convertbits',
                       spec=segwit_addr.convertbits)
    @mock.patch.object(segwit_addr, 'bech32_encode',
                       spec=segwit_addr.bech32_encode)
    @mock.patch.object(segwit_addr, 'decode',
                       spec=segwit_addr.decode)
    def test_encode(self, md, mbe, mcb):
        mcb.return_value = ['foo']
        mbe.return_value = 'bar'
        md.return_value = (None, None)
        self.assertEqual(None, segwit_addr.encode('bc', 5, [0, 1, 2]))
        mcb.assert_called_once_with([0, 1, 2], 8, 5)
        mbe.assert_called_once_with('bc', [5, 'foo'])
        md.assert_called_once_with('bc', 'bar')
        mcb.reset_mock()
        mbe.reset_mock()
        md.reset_mock()
        md.return_value = (3, [6, 7, 8])
        self.assertEqual('bar', segwit_addr.encode('ltc', 9, [3, 2, 1]))
        mcb.assert_called_once_with([3, 2, 1], 8, 5)
        mbe.assert_called_once_with('ltc', [9, 'foo'])
        md.assert_called_once_with('ltc', 'bar')

class IntegrationTest(unittest.TestCase):
    VALID_ADDRESS = [
        ["BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4",
          "0014751e76e8199196d454941c45d1b3a323f1433bd6"],
        ["tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7",
         "00201863143c14c5166804bd19203356da136c985678cd4d27a1b8c6329604903262"],
        ["bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7k7grplx",
         "5128751e76e8199196d454941c45d1b3a323f1433bd6751e76e8199196d454941c45d1b3a323f1433bd6"],
        ["BC1SW50QA3JX3S", "6002751e"],
        ["bc1zw508d6qejxtdg4y5r3zarvaryvg6kdaj",
         "5210751e76e8199196d454941c45d1b3a323"],
        ["tb1qqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvsesrxh6hy",
         "0020000000c4a5cad46221b2a187905e5266362b99d5e91c6ce24d165dab93e86433"],
    ]
    
    INVALID_ADDRESS = [
        "tc1qw508d6qejxtdg4y5r3zarvbry0c5xw7kg3g4ty",
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5",
        "BC13W508D6QEJXTDG4Y5R3ZARVARY0C5XW7KN40WF2",
        "bc1rw5uspcuh",
        "bc10w508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kw5rljs90",
        "BC1QR508D6QEJXTDG4Y5R3ZARVARYV98GJ9P",
        "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sL5k7",
        "bc1zw508d6qejxtdg4y5r3zarvaryvqyzf3du",
        "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3pjxtptv",
        "bc1gmk9yu",
    ]

    def setUp(self):
        self.longMessage = True

    @staticmethod
    def get_hrp(addr):
        return ''.join(addr[:addr.find('1')]).lower()

    def test_valid_addresses(self):
        for addr, script in self.VALID_ADDRESS:
            hrp = self.get_hrp(addr)
            witver, witprog = segwit_addr.decode(hrp, addr)
            self.assertEqual(addr.lower(),
                             segwit_addr.encode(hrp, witver, witprog),
                             "Address %s failed." % addr)

    def test_invalid_addresess(self):
        for addr in self.INVALID_ADDRESS:
            hrp = self.get_hrp(addr)
            self.assertEqual((None, None), segwit_addr.decode(hrp, addr),
                             "Address %s failed." % addr)
