import unittest

from p2pool.bitcoin import getwork, data as bitcoin_data

class Test(unittest.TestCase):
    def test_all(self):
        cases = [
            {
                'target': '0000000000000000000000000000000000000000000000f2b944000000000000',
                'midstate': '5982f893102dec03e374b472647c4f19b1b6d21ae4b2ac624f3d2f41b9719404',
                'hash1': '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
                'data': '0000000163930d52a5ffca79b29b95a659a302cd4e1654194780499000002274000000002e133d9e51f45bc0886d05252038e421e82bff18b67dc14b90d9c3c2f422cd5c4dd4598e1a44b9f200000000000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000'
            },
            {
                'midstate' : 'f4a9b048c0cb9791bc94b13ee0eec21e713963d524fd140b58bb754dd7b0955f',
                'data' : '000000019a1d7342fb62090bda686b22d90f9f73d0f5c418b9c980cd0000011a00000000680b07c8a2f97ecd831f951806857e09f98a3b81cdef1fa71982934fef8dc3444e18585d1a0abbcf00000000000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000',
                'hash1' : '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
                'target' : '0000000000000000000000000000000000000000000000cfbb0a000000000000',
                'extrathing': 'hi!',
            },
            {
                'data' : '000000019a1d7342fb62090bda686b22d90f9f73d0f5c418b9c980cd0000011a00000000680b07c8a2f97ecd831f951806857e09f98a3b81cdef1fa71982934fef8dc3444e18585d1a0abbcf00000000000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000',
                'hash1' : '00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000',
                'target' : '0000000000000000000000000000000000000000000000cfbb0a000000000000',
                'extrathing': 'hi!',
            },
        ]
        for case in cases:
            ba = getwork.BlockAttempt.from_getwork(case)
            
            extra = dict(case)
            del extra['data'], extra['hash1'], extra['target']
            extra.pop('midstate', None)
            
            getwork_check = ba.getwork(**extra)
            assert getwork_check == case or dict((k, v) for k, v in getwork_check.iteritems() if k != 'midstate') == case
        
        case2s = [
            getwork.BlockAttempt(
                1,
                0x148135e10208db85abb62754341a392eab1f186aab077a831cf7,
                0x534ea08be1ab529f484369344b6d5423ef5a0767db9b3ebb4e182bbb67962520,
                1305759879,
                bitcoin_data.FloatingInteger.from_target_upper_bound(0x44b9f20000000000000000000000000000000000000000000000),
                0x44b9f20000000000000000000000000000000000000000000000,
            ),
            getwork.BlockAttempt(
                1,
                0x148135e10208db85abb62754341a392eab1f186aab077a831cf7,
                0x534ea08be1ab529f484369344b6d5423ef5a0767db9b3ebb4e182bbb67962520,
                1305759879,
                bitcoin_data.FloatingInteger.from_target_upper_bound(0x44b9f20000000000000000000000000000000000000000000000),
                432*2**230,
            ),
            getwork.BlockAttempt(
                1,
                0x148135e10208db85abb62754341a392eab1f186aab077a831cf7,
                0x534ea08be1ab529f484369344b6d5423ef5a0767db9b3ebb4e182bbb67962520,
                1305759879,
                bitcoin_data.FloatingInteger.from_target_upper_bound(0x44b9f20000000000000000000000000000000000000000000000),
                7*2**240,
            )
        ]
        for case2 in case2s:
            assert getwork.BlockAttempt.from_getwork(case2.getwork()) == case2
            assert getwork.BlockAttempt.from_getwork(case2.getwork(ident='hi')) == case2
            case2 = case2.update(previous_block=case2.previous_block - 10)
            assert getwork.BlockAttempt.from_getwork(case2.getwork()) == case2
            assert getwork.BlockAttempt.from_getwork(case2.getwork(ident='hi')) == case2
