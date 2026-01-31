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

from p2pool.util import cash_addr
from p2pool.bitcoin import data

class UnitTest(unittest.TestCase):

    def setUp(self):
        self.longMessage = True

    def test_polymod(self):
        data = [([2, 9, 20, 3, 15, 9, 14, 3, 1, 19, 8, 0, 0, 2, 2, 6, 16, 14, 0,
                  31, 14, 2, 25, 30, 24, 15, 8, 18, 7, 27, 14, 25, 31, 7, 31,
                  21, 0, 17, 14, 0, 22, 15, 22, 3, 31, 28, 30, 18, 24, 23, 7, 7,
                  8, 12], 0),
                ([2, 9, 20, 3, 15, 9, 14, 3, 1, 19, 8, 0, 0, 2, 2, 6, 16, 14, 0,
                  31, 14, 2, 25, 30, 24, 15, 8, 18, 7, 27, 14, 25, 31, 7, 31,
                  21, 0, 17, 14, 0, 22, 15, 22, 3, 31, 28, 0, 0, 0, 0, 0, 0, 0,
                  0], 1050949164300),
                ([2, 9, 20, 3, 15, 9, 14, 3, 1, 19, 8, 0, 1, 0, 22, 23, 5, 29,
                  23, 9, 18, 15, 26, 5, 0, 12, 7, 31, 26, 25, 4, 16, 4, 28, 9,
                  29, 2, 1, 25, 21, 9, 13, 18, 0, 17, 28, 21, 23, 19, 29, 17,
                  10, 17, 18], 0),
                ([2, 9, 20, 3, 15, 9, 14, 3, 1, 19, 8, 0, 1, 0, 22, 23, 5, 29,
                  23, 9, 18, 15, 26, 5, 0, 12, 7, 31, 26, 25, 4, 16, 4, 28, 9,
                  29, 2, 1, 25, 21, 9, 13, 18, 0, 17, 28, 0, 0, 0, 0, 0, 0, 0,
                  0], 746919078450)
               ]
        for d, r in data:
            self.assertEqual(r, cash_addr.polymod(d))

    def test_expand_prefix(self):
        data = [('bitcoincash', [2, 9, 20, 3, 15, 9, 14, 3, 1, 19, 8, 0]),
                ('bchtest', [2, 3, 8, 20, 5, 19, 20, 0]),
                ('perf', [16, 5, 18, 6, 0]),
                ('bc', [2, 3, 0]),
               ]
        for d, r in data:
            self.assertEqual(r, cash_addr.expand_prefix(d),
                             "Prefix %s failed." % d)

    @mock.patch.object(cash_addr, 'expand_prefix', spec=cash_addr.expand_prefix)
    @mock.patch.object(cash_addr, 'polymod', spec=cash_addr.polymod)
    def test_verify_checksum(self, mp, mep):
        mep.return_value = ['foo']
        mp.return_value = 1
        data = [('bitcoincash', [0, 14, 20, 15, 7, 13, 26, 0, 25, 18, 6, 11, 13,
                                 8, 21, 4, 20, 3, 17, 2, 29, 3, 12, 29, 3, 4,
                                 15, 24, 20, 6, 14, 30, 22, 12, 7, 9, 17, 11, 21]),
                ('bchtest', [0, 30, 18, 12, 16, 17, 29, 3, 7, 15, 6, 6, 25, 6,
                             25, 13, 22, 3, 25, 23, 4, 29, 26, 9, 26, 18, 31, 0,
                             0, 27, 14, 13, 1, 14, 7, 1, 6, 3, 0]),
               ]
        self.assertFalse(cash_addr.verify_checksum(*data[0]))
        mep.assert_called_once_with(data[0][0])
        mp.assert_called_once_with(['foo'] + data[0][1])
        mep.reset_mock()
        mp.reset_mock()
        mep.return_value = ['bar']
        mp.return_value = 0
        self.assertTrue(cash_addr.verify_checksum(*data[1]))
        mep.assert_called_once_with(data[1][0])
        mp.assert_called_once_with(['bar'] + data[1][1])
        mp.return_value = 2
        self.assertFalse(cash_addr.verify_checksum(*data[1]))

    @mock.patch.object(cash_addr, 'expand_prefix', spec=cash_addr.expand_prefix)
    @mock.patch.object(cash_addr, 'polymod', spec=cash_addr.polymod)
    def test_create_checksum(self, mp, mep):
        mep.return_value = ['foo']
        data = [('bitcoincash', 1, [0, 0, 0, 0, 0, 0, 0, 1]),
                ('bchtest', 0, [0, 0, 0, 0, 0, 0, 0, 0]),
                ('perf', 410305908, [0, 0, 12, 7, 9, 17, 11, 20]),
                ('junk', 309275181844, [9, 0, 1, 3, 25, 16, 24, 20]),
               ]
        for p, d, r in data:
            mep.reset_mock()
            mp.reset_mock()
            mp.return_value = d
            self.assertListEqual(r, cash_addr.create_checksum(p, ['bar']),
                                 "%s, %s failed." % (p, d))
            mep.assert_called_once_with(p)
            mp.assert_called_once_with(['foo'] + ['bar'] + [0] * 8)

    @mock.patch.object(cash_addr, 'create_checksum', spec=cash_addr.create_checksum)
    def test_assemble(self, mcc):
        data = [('bitcoincash', [0, 2, 2, 6, 16, 14, 0, 31, 14, 2, 25, 30, 24,
                                 15, 8, 18, 7, 27, 14, 25, 31, 7, 31, 21, 0, 17,
                                 14, 0, 22, 15, 22, 3, 31, 28],
                 [30, 18, 24, 23, 7, 7, 8, 12],
                 'bitcoincash:qzzxswqlwze7c0gj8mwel8l4q3wqk0krlu7jch88gv',
                ),
                ('bitcoincash', [1, 0, 22, 23, 5, 29, 23, 9, 18, 15, 26, 5, 0,
                                 12, 7, 31, 26, 25, 4, 16, 4, 28, 9, 29, 2, 1,
                                 25, 21, 9, 13, 18, 0, 17, 28],
                 [21, 23, 19, 29, 17, 10, 17, 18],
                 'bitcoincash:pqkh9ahfj069qv8l6eysyufazpe4fdjq3u4hna323j',
                ),
               ]
        for p, d, c, r in data:
            mcc.reset_mock()
            mcc.return_value = c
            self.assertEqual(r, cash_addr.assemble(p, d))
            mcc.assert_called_once_with(p, d)

    @mock.patch.object(cash_addr, 'convertbits', spec=cash_addr.convertbits)
    def test_valid_version(self, mcb):
        mcb.return_value = None
        self.assertFalse(cash_addr.valid_version([1, 2, 3, 4]))
        mcb.reset_mock()
        mcb.return_value = [1<<8, 0]
        self.assertFalse(cash_addr.valid_version([1, 2, 3, 4]))
        mcb.assert_called_once_with([1, 2, 3, 4], 5, 8, False)
        for ver in range(1<<4 - 1):
            for i in range(100):
                mcb.return_value = [ver] + [0] * i
                if ver == 0 and i == 20:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                elif ver == 1 and i == 24:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                elif ver == 2 and i == 28:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                elif ver == 3 and i == 32:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                elif ver == 4 and i == 40:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                elif ver == 5 and i == 48:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                elif ver == 6 and i == 56:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                elif ver == 7 and i == 64:
                    self.assertTrue(cash_addr.valid_version([0]),
                                    "Failed for version %s and %d bytes." % (ver, i))
                else:
                    self.assertFalse(cash_addr.valid_version([0]),
                                     "Failed for version %s and %d bytes." % (ver, i))
        
    @mock.patch.object(cash_addr, 'valid_version', spec=cash_addr.valid_version)
    @mock.patch.object(cash_addr, 'verify_checksum', spec=cash_addr.verify_checksum)
    def test_disassemble(self, mvc, mvv):
        mvv.return_value = False
        def_prefix = 'bitcoincash'
        # Test non-numeric and non-alpha range
        for i in range(33):
            self.assertTupleEqual((None, None),
                                  cash_addr.disassemble(chr(i), def_prefix))
        for i in range(127, 256):
            self.assertTupleEqual((None, None),
                                  cash_addr.disassemble(chr(i), def_prefix))
        # Test mixed case
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble('acDefghjk', def_prefix))
        # Test address too short
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble('bitcoincash:acdefghj', def_prefix))
        # Test address too long
        addr = 'bitcoincash:' + 'a' * 113
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble(addr, def_prefix))
        # Test illegal characters
        addr = 'bitcoincash:bcdefghjklm'
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble(addr, def_prefix))
        addr = 'bitcoincash:acdefghijklm'
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble(addr, def_prefix))
        addr = 'bitcoincash:acdefghijklm1'
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble(addr, def_prefix))
        # Check that bech32_verify_checksum hasn't been called.
        self.assertEqual(0, mvc.call_count)
        addr = 'bitcoincash:pqkh9ahfj069qv8l6eysyufazpe4fdjq3u4hna323j'
        # Test that the header check failed
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble(addr, def_prefix))
        mvv.return_value = True
        # Test that the checksum failed
        mvc.return_value = 0
        mvv.reset_mock()
        data = [1, 0, 22, 23, 5, 29, 23, 9, 18, 15, 26, 5, 0, 12, 7, 31, 26, 25,
                4, 16, 4, 28, 9, 29, 2, 1, 25, 21, 9, 13, 18, 0, 17, 28, 21, 23,
                19, 29, 17, 10, 17, 18]
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble(addr, def_prefix))
        mvc.assert_called_once_with('bitcoincash', data)
        mvv.assert_called_once_with(data[:-8])
        mvc.reset_mock()
        # Test address without prefix
        srt_addr = addr[12:]
        self.assertTupleEqual((None, None),
                              cash_addr.disassemble(srt_addr, def_prefix))
        mvc.assert_called_once_with('bitcoincash', data)
        mvc.return_value = 1
        self.assertTupleEqual(('bitcoincash', data[:-8]),
                              cash_addr.disassemble(addr, def_prefix))
        # Test with different prefix
        mvc.reset_mock()
        self.assertTupleEqual(('bchtest', data[:-8]),
                              cash_addr.disassemble(srt_addr, 'bchtest'))
        mvc.assert_called_once_with('bchtest', data)

    @mock.patch.object(cash_addr, 'disassemble', spec=cash_addr.disassemble)
    @mock.patch.object(cash_addr, 'convertbits', spec=cash_addr.convertbits)
    def test_decode(self, mcb, md):
        data = [0, 1, 2, 3, 4, 5]
        md.return_value = ('bchtest', data)
        addr = 'bitcoincash:qzzxswqlwze7c0gj8mwel8l4q3wqk0krlu7jch88gv'
        pfix = 'bitcoincash'
        # Test wrong prefix
        self.assertTupleEqual((None, None), cash_addr.decode(pfix, addr))
        md.assert_called_once_with(addr, pfix)
        md.reset_mock()
        self.assertTupleEqual((None, None), cash_addr.decode(pfix, addr[12:]))
        md.assert_called_once_with(addr[12:], pfix)
        self.assertEqual(0, mcb.call_count)
        # Test bad convertbits
        mcb.return_value = None
        md.return_value = (pfix, data)
        self.assertTupleEqual((None, None), cash_addr.decode(pfix, addr))
        mcb.assert_called_once_with(data, 5, 8, False)
        mcb.return_value = []
        self.assertTupleEqual((None, None), cash_addr.decode(pfix, addr))
        # Test version
        mcb.return_value = [0, 5, 4, 3]
        self.assertTupleEqual((0, [5, 4, 3]), cash_addr.decode(pfix, addr))
        mcb.return_value = [8, 1, 2, 3]
        self.assertTupleEqual((1, [1, 2, 3]), cash_addr.decode(pfix, addr))

    @mock.patch.object(cash_addr, 'convertbits', spec=cash_addr.convertbits)
    @mock.patch.object(cash_addr, 'assemble', spec=cash_addr.assemble)
    @mock.patch.object(cash_addr, 'decode', spec=cash_addr.decode)
    def test_encode(self, md, mba, mcb):
        mcb.return_value = ['foo']
        mba.return_value = 'bar'
        md.return_value = (None, None)
        # Test for invalid data lengths.
        valid_lengths = [20, 24, 28, 32, 40, 48, 56, 64]
        data = []
        self.assertEqual(None, cash_addr.encode('bchtest', 0, data))
        for i in range(1, 129):
            data.append(i)
            if i in valid_lengths:
                continue
            self.assertEqual(None, cash_addr.encode('bchtest', 0, data))
        # Test unsupported versions.
        data = [x for x in range(20)]
        for i in range(2, 15):
            self.assertEqual(None, cash_addr.encode('bchtest', i, [0]))
        self.assertEqual(None, cash_addr.encode('bitcoincash', 0, data))
        mcb.assert_called_once_with([0] + data, 8, 5)
        mba.assert_called_once_with('bitcoincash', ['foo'])
        md.assert_called_once_with('bitcoincash', 'bar')
        mcb.reset_mock()
        mba.reset_mock()
        md.reset_mock()
        md.return_value = (3, [6, 7, 8])
        self.assertEqual('bar', cash_addr.encode('bchtest', 1, data))
        mcb.assert_called_once_with([8] + data, 8, 5)
        mba.assert_called_once_with('bchtest', ['foo'])
        md.assert_called_once_with('bchtest', 'bar')
        mcb.reset_mock()
        self.assertEqual('bar', cash_addr.encode('bchtest', 15, data))
        mcb.assert_called_once_with([120] + data, 8, 5)
        for i in range(8):
            mcb.reset_mock()
            data = [x for x in range(valid_lengths[i])]
            self.assertEqual('bar', cash_addr.encode('bchtest', 0, data))
            mcb.assert_called_once_with([i] + data, 8, 5)

class IntegrationTest(unittest.TestCase):
    OLD_NEW_ADDRESS = [
        ('1BpEi6DfDAUFd7GtittLSdBeYJvcoaVggu',
         'bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a'),
        ('1KXrWXciRDZUpQwQmuM1DbwsKDLYAYsVLR',
         'bitcoincash:qr95sy3j9xwd2ap32xkykttr4cvcu7as4y0qverfuy'),
        ('16w1D5WRVKJuZUsSRzdLp9w3YGcgoxDXb',
         'bitcoincash:qqq3728yw0y47sqn6l2na30mcw6zm78dzqre909m2r'),
        ('3CWFddi6m4ndiGyKqzYvsFYagqDLPVMTzC',
         'bitcoincash:ppm2qsznhks23z7629mms6s4cwef74vcwvn0h829pq'),
        ('3LDsS579y7sruadqu11beEJoTjdFiFCdX4',
         'bitcoincash:pr95sy3j9xwd2ap32xkykttr4cvcu7as4yc93ky28e'),
        ('31nwvkZwyPdgzjBJZXfDmSWsC4ZLKpYyUw',
         'bitcoincash:pqq3728yw0y47sqn6l2na30mcw6zm78dzq5ucqzc37'),
    ]

    VALID_ADDRESS = [
         ['bitcoincash:qqqxkp0kxgul03wats0ke54qp3xrtq63kudgp05fkn', '006B05F63239F7C5DD5C1F6CD2A00C4C358351B7'],
	 ['bitcoincash:qr6m7j9njldwwzlg9v7v53unlr4jkmx6eylep8ekg2', 'F5BF48B397DAE70BE82B3CCA4793F8EB2B6CDAC9'],
	 ['bchtest:pr6m7j9njldwwzlg9v7v53unlr4jkmx6eyvwc0uz5t', 'F5BF48B397DAE70BE82B3CCA4793F8EB2B6CDAC9'],
	 ['pref:pr6m7j9njldwwzlg9v7v53unlr4jkmx6ey65nvtks5', 'F5BF48B397DAE70BE82B3CCA4793F8EB2B6CDAC9'],
	 ['prefix:0r6m7j9njldwwzlg9v7v53unlr4jkmx6ey3qnjwsrf', 'F5BF48B397DAE70BE82B3CCA4793F8EB2B6CDAC9'],
	 ['bitcoincash:q9adhakpwzztepkpwp5z0dq62m6u5v5xtyj7j3h2ws4mr9g0', '7ADBF6C17084BC86C1706827B41A56F5CA32865925E946EA'],
	 ['bchtest:p9adhakpwzztepkpwp5z0dq62m6u5v5xtyj7j3h2u94tsynr', '7ADBF6C17084BC86C1706827B41A56F5CA32865925E946EA'],
	 ['pref:p9adhakpwzztepkpwp5z0dq62m6u5v5xtyj7j3h2khlwwk5v', '7ADBF6C17084BC86C1706827B41A56F5CA32865925E946EA'],
	 ['prefix:09adhakpwzztepkpwp5z0dq62m6u5v5xtyj7j3h2p29kc2lp', '7ADBF6C17084BC86C1706827B41A56F5CA32865925E946EA'],
	 ['bitcoincash:qgagf7w02x4wnz3mkwnchut2vxphjzccwxgjvvjmlsxqwkcw59jxxuz', '3A84F9CF51AAE98A3BB3A78BF16A6183790B18719126325BFC0C075B'],
	 ['bchtest:pgagf7w02x4wnz3mkwnchut2vxphjzccwxgjvvjmlsxqwkcvs7md7wt', '3A84F9CF51AAE98A3BB3A78BF16A6183790B18719126325BFC0C075B'],
	 ['pref:pgagf7w02x4wnz3mkwnchut2vxphjzccwxgjvvjmlsxqwkcrsr6gzkn', '3A84F9CF51AAE98A3BB3A78BF16A6183790B18719126325BFC0C075B'],
	 ['prefix:0gagf7w02x4wnz3mkwnchut2vxphjzccwxgjvvjmlsxqwkc5djw8s9g', '3A84F9CF51AAE98A3BB3A78BF16A6183790B18719126325BFC0C075B'],
	 ['bitcoincash:qvch8mmxy0rtfrlarg7ucrxxfzds5pamg73h7370aa87d80gyhqxq5nlegake', '3173EF6623C6B48FFD1A3DCC0CC6489B0A07BB47A37F47CFEF4FE69DE825C060'],
	 ['bchtest:pvch8mmxy0rtfrlarg7ucrxxfzds5pamg73h7370aa87d80gyhqxq7fqng6m6', '3173EF6623C6B48FFD1A3DCC0CC6489B0A07BB47A37F47CFEF4FE69DE825C060'],
	 ['pref:pvch8mmxy0rtfrlarg7ucrxxfzds5pamg73h7370aa87d80gyhqxq4k9m7qf9', '3173EF6623C6B48FFD1A3DCC0CC6489B0A07BB47A37F47CFEF4FE69DE825C060'],
	 ['prefix:0vch8mmxy0rtfrlarg7ucrxxfzds5pamg73h7370aa87d80gyhqxqsh6jgp6w', '3173EF6623C6B48FFD1A3DCC0CC6489B0A07BB47A37F47CFEF4FE69DE825C060'],
	 ['bitcoincash:qnq8zwpj8cq05n7pytfmskuk9r4gzzel8qtsvwz79zdskftrzxtar994cgutavfklv39gr3uvz', 'C07138323E00FA4FC122D3B85B9628EA810B3F381706385E289B0B25631197D194B5C238BEB136FB'],
	 ['bchtest:pnq8zwpj8cq05n7pytfmskuk9r4gzzel8qtsvwz79zdskftrzxtar994cgutavfklvmgm6ynej', 'C07138323E00FA4FC122D3B85B9628EA810B3F381706385E289B0B25631197D194B5C238BEB136FB'],
	 ['pref:pnq8zwpj8cq05n7pytfmskuk9r4gzzel8qtsvwz79zdskftrzxtar994cgutavfklv0vx5z0w3', 'C07138323E00FA4FC122D3B85B9628EA810B3F381706385E289B0B25631197D194B5C238BEB136FB'],
	 ['prefix:0nq8zwpj8cq05n7pytfmskuk9r4gzzel8qtsvwz79zdskftrzxtar994cgutavfklvwsvctzqy', 'C07138323E00FA4FC122D3B85B9628EA810B3F381706385E289B0B25631197D194B5C238BEB136FB'],
	 ['bitcoincash:qh3krj5607v3qlqh5c3wq3lrw3wnuxw0sp8dv0zugrrt5a3kj6ucysfz8kxwv2k53krr7n933jfsunqex2w82sl', 'E361CA9A7F99107C17A622E047E3745D3E19CF804ED63C5C40C6BA763696B98241223D8CE62AD48D863F4CB18C930E4C'],
	 ['bchtest:ph3krj5607v3qlqh5c3wq3lrw3wnuxw0sp8dv0zugrrt5a3kj6ucysfz8kxwv2k53krr7n933jfsunqnzf7mt6x', 'E361CA9A7F99107C17A622E047E3745D3E19CF804ED63C5C40C6BA763696B98241223D8CE62AD48D863F4CB18C930E4C'],
	 ['pref:ph3krj5607v3qlqh5c3wq3lrw3wnuxw0sp8dv0zugrrt5a3kj6ucysfz8kxwv2k53krr7n933jfsunqjntdfcwg', 'E361CA9A7F99107C17A622E047E3745D3E19CF804ED63C5C40C6BA763696B98241223D8CE62AD48D863F4CB18C930E4C'],
	 ['prefix:0h3krj5607v3qlqh5c3wq3lrw3wnuxw0sp8dv0zugrrt5a3kj6ucysfz8kxwv2k53krr7n933jfsunqakcssnmn', 'E361CA9A7F99107C17A622E047E3745D3E19CF804ED63C5C40C6BA763696B98241223D8CE62AD48D863F4CB18C930E4C'],
	 ['bitcoincash:qmvl5lzvdm6km38lgga64ek5jhdl7e3aqd9895wu04fvhlnare5937w4ywkq57juxsrhvw8ym5d8qx7sz7zz0zvcypqscw8jd03f', 'D9FA7C4C6EF56DC4FF423BAAE6D495DBFF663D034A72D1DC7D52CBFE7D1E6858F9D523AC0A7A5C34077638E4DD1A701BD017842789982041'],
         ['bchtest:pmvl5lzvdm6km38lgga64ek5jhdl7e3aqd9895wu04fvhlnare5937w4ywkq57juxsrhvw8ym5d8qx7sz7zz0zvcypqs6kgdsg2g', 'D9FA7C4C6EF56DC4FF423BAAE6D495DBFF663D034A72D1DC7D52CBFE7D1E6858F9D523AC0A7A5C34077638E4DD1A701BD017842789982041'],
	 ['pref:pmvl5lzvdm6km38lgga64ek5jhdl7e3aqd9895wu04fvhlnare5937w4ywkq57juxsrhvw8ym5d8qx7sz7zz0zvcypqsammyqffl', 'D9FA7C4C6EF56DC4FF423BAAE6D495DBFF663D034A72D1DC7D52CBFE7D1E6858F9D523AC0A7A5C34077638E4DD1A701BD017842789982041'],
	 ['prefix:0mvl5lzvdm6km38lgga64ek5jhdl7e3aqd9895wu04fvhlnare5937w4ywkq57juxsrhvw8ym5d8qx7sz7zz0zvcypqsgjrqpnw8', 'D9FA7C4C6EF56DC4FF423BAAE6D495DBFF663D034A72D1DC7D52CBFE7D1E6858F9D523AC0A7A5C34077638E4DD1A701BD017842789982041'],
	 ['bitcoincash:qlg0x333p4238k0qrc5ej7rzfw5g8e4a4r6vvzyrcy8j3s5k0en7calvclhw46hudk5flttj6ydvjc0pv3nchp52amk97tqa5zygg96mtky5sv5w', 'D0F346310D5513D9E01E299978624BA883E6BDA8F4C60883C10F28C2967E67EC77ECC7EEEAEAFC6DA89FAD72D11AC961E164678B868AEEEC5F2C1DA08884175B'],
	 ['bchtest:plg0x333p4238k0qrc5ej7rzfw5g8e4a4r6vvzyrcy8j3s5k0en7calvclhw46hudk5flttj6ydvjc0pv3nchp52amk97tqa5zygg96mc773cwez', 'D0F346310D5513D9E01E299978624BA883E6BDA8F4C60883C10F28C2967E67EC77ECC7EEEAEAFC6DA89FAD72D11AC961E164678B868AEEEC5F2C1DA08884175B'],
	 ['pref:plg0x333p4238k0qrc5ej7rzfw5g8e4a4r6vvzyrcy8j3s5k0en7calvclhw46hudk5flttj6ydvjc0pv3nchp52amk97tqa5zygg96mg7pj3lh8', 'D0F346310D5513D9E01E299978624BA883E6BDA8F4C60883C10F28C2967E67EC77ECC7EEEAEAFC6DA89FAD72D11AC961E164678B868AEEEC5F2C1DA08884175B'],
	 ['prefix:0lg0x333p4238k0qrc5ej7rzfw5g8e4a4r6vvzyrcy8j3s5k0en7calvclhw46hudk5flttj6ydvjc0pv3nchp52amk97tqa5zygg96ms92w6845', 'D0F346310D5513D9E01E299978624BA883E6BDA8F4C60883C10F28C2967E67EC77ECC7EEEAEAFC6DA89FAD72D11AC961E164678B868AEEEC5F2C1DA08884175B'],
    ]
    
    INVALID_ADDRESS = [
        'bitcoincash1qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a',
        'bitcoincash:qr95sy3j9xwd2Ap32xkykttr4cvcu7as4y0qverfuy',
        'bitcoincash:qqq3728yw0y57sqn6l2na30mcw6zm78dzqre909m2r',
        'bitcoincash:ppm2qsznhks2z7629mms6s4cwef74vcwvn0h829pq',
        'bitcoincash:pr95sy3j9xwd2ap32xkykettr4cvcu7as4yc93ky28e',
    ]

    def setUp(self):
        self.longMessage = True

    @staticmethod
    def get_prefix(addr):
        try:
            return ''.join(addr[:addr.find(':')]).lower()
        except TypeError:
            return 'bitcoincash'

    @staticmethod
    def to_byte_array(data):
        return [ord(x) for x in data]

    def test_old_and_new_addresses_match(self):
        for oaddr, naddr in self.OLD_NEW_ADDRESS:
            # Base58 has 4 bytes of checksum
            odata = self.to_byte_array(data.base58_decode(oaddr))[:-4]
            for prefix in [True, False]:
                addr = naddr if prefix else naddr[12:]
                # cashaddr.decode already removes the 5 bytes of checksum
                nver, ndata = cash_addr.decode('bitcoincash', naddr)
                self.assertTrue(odata[0] in [0, 5],
                                "Old address %s is not a valid version" % oaddr)
                self.assertTrue(ndata[0] & 8 in [0, 8],
                                "New address %s in not a valid type" % naddr)
                if odata[0] == 0:
                    self.assertEqual(0, nver, "Bad version for %s" % naddr)
                elif odata[0] == 5:
                    self.assertEqual(1, nver, "Bad version for %s" % naddr)
                self.assertListEqual(odata[1:], ndata,
                        "Old address %s and new address %s don't have the same payload."
                            % (oaddr, naddr))

    def test_valid_addresses(self):
        for addr, script in self.VALID_ADDRESS:
            prefix = self.get_prefix(addr)
            ver, data = cash_addr.decode(prefix, addr)
            self.assertEqual(addr.lower(),
                             cash_addr.encode(prefix, ver, data),
                             "Address %s failed." % addr)

    def test_invalid_addresess(self):
        for addr in self.INVALID_ADDRESS:
            prefix = self.get_prefix(addr)
            self.assertEqual((None, None), cash_addr.decode(prefix, addr),
                             "Address %s failed." % addr)
