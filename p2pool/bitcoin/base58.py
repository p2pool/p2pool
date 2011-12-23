from p2pool.util import bases

_alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def encode(bindata):
    bindata2 = bindata.lstrip(chr(0))
    return _alphabet[0]*(len(bindata) - len(bindata2)) + bases.natural_to_string(bases.string_to_natural(bindata2), _alphabet)

def decode(b58data):
    b58data2 = b58data.lstrip(_alphabet[0])
    return chr(0)*(len(b58data) - len(b58data2)) + bases.natural_to_string(bases.string_to_natural(b58data2, _alphabet))
