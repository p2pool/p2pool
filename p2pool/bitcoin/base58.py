from p2pool.util import bases

base58_alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def base58_encode(data):
    return base58_alphabet[0]*(len(data) - len(data.lstrip(chr(0)))) + bases.natural_to_string(bases.string_to_natural(data), base58_alphabet)

def base58_decode(data):
    return chr(0)*(len(data) - len(data.lstrip(base58_alphabet[0]))) + bases.natural_to_string(bases.string_to_natural(data.lstrip(base58_alphabet[0]), base58_alphabet))

