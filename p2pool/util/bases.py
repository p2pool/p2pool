def natural_to_string(n, alphabet=None):
    if n < 0:
        raise TypeError('n must be a natural')
    if alphabet is None:
        s = '%x' % (n,)
        if len(s) % 2:
            s = '0' + s
        return s.decode('hex')
    else:
        assert len(set(alphabet)) == len(alphabet)
        res = []
        while n:
            n, x = divmod(n, len(alphabet))
            res.append(alphabet[x])
        res.reverse()
        return ''.join(res)

def string_to_natural(s, alphabet=None):
    if alphabet is None:
        assert not s.startswith('\x00')
        return int(s.encode('hex'), 16) if s else 0
    else:
        assert len(set(alphabet)) == len(alphabet)
        assert not s.startswith(alphabet[0])
        return sum(alphabet.index(char) * len(alphabet)**i for i, char in enumerate(reversed(s)))
