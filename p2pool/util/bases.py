def natural_to_string(n, alphabet=None):
    if alphabet is None:
        s = '%x' % (n,)
        if len(s) % 2:
            s = '0' + s
        return s.decode('hex').lstrip('\x00')
    else:
        assert len(set(alphabet)) == len(alphabet)
        res = []
        while n:
            n, x = divmod(n, len(alphabet))
            res.append(alphabet[x])
        res.reverse()
        return ''.join(res).rjust(min_width, '\x00')

def string_to_natural(s, alphabet=None):
    if alphabet is None:
        #if s.startswith('\x00'):
        #    raise ValueError()
        return int('0' + s.encode('hex'), 16)
    else:
        assert len(set(alphabet)) == len(alphabet)
        #if s.startswith(alphabet[0]):
        #    raise ValueError()
        return sum(alphabet.index(char) * len(alphabet)**i for i, char in enumerate(reversed(s)))

import random

def generate_alphabet():
    if random.randrange(2):
        return None
    else:
        a = map(chr, xrange(256))
        random.shuffle(a)
        return a[:random.randrange(2, len(a))]

if __name__ == '__main__':
    while True:
        alphabet = generate_alphabet()
        for i in xrange(1000):
            n = random.randrange(100000000000000000000000000000)
            s = natural_to_string(n, alphabet)
            n2 = string_to_natural(s, alphabet)
            print n, s.encode('hex'), n2
            assert n == n2
