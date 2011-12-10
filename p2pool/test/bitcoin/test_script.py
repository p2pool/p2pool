import unittest

from p2pool.bitcoin import script

class Test(unittest.TestCase):
    def test_all(self):
        data = '76  A9  14 89 AB CD EF AB BA AB BA AB BA AB BA AB BA AB BA AB BA AB BA  88 AC'.replace(' ', '').decode('hex')
        self.assertEquals(
            list(script.parse(data)),
            [('UNK_118', ''), ('UNK_169', ''), ('PUSH20', '\x89\xab\xcd\xef\xab\xba\xab\xba\xab\xba\xab\xba\xab\xba\xab\xba\xab\xba\xab\xba'), ('UNK_136', ''), ('CHECKSIG', '')],
        )
        self.assertEquals(script.get_sigop_count(data), 1)
