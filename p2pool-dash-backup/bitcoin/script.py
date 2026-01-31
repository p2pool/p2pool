from p2pool.util import math, pack
import cStringIO as StringIO

def reads_nothing(f):
    return None, f
def protoPUSH(length):
    return lambda f: f.read(length)
def protoPUSHDATA(size_len):
    def _(f):
        length_str = f.read(size_len)
        length = math.string_to_natural(length_str[::-1].lstrip(chr(0)))
        data = f.read(length)
        return data
    return _

opcodes = {}
for i in xrange(256):
    opcodes[i] = 'UNK_' + str(i), reads_nothing

opcodes[0] = 'PUSH', lambda f: ('', f)
for i in xrange(1, 76):
    opcodes[i] = 'PUSH', protoPUSH(i)
opcodes[76] = 'PUSH', protoPUSHDATA(1)
opcodes[77] = 'PUSH', protoPUSHDATA(2)
opcodes[78] = 'PUSH', protoPUSHDATA(4)
opcodes[79] = 'PUSH', lambda f: ('\x81', f)
for i in xrange(81, 97):
    opcodes[i] = 'PUSH', lambda f, _i=i: (chr(_i - 80), f)

opcodes[172] = 'CHECKSIG', reads_nothing
opcodes[173] = 'CHECKSIGVERIFY', reads_nothing
opcodes[174] = 'CHECKMULTISIG', reads_nothing
opcodes[175] = 'CHECKMULTISIGVERIFY', reads_nothing

def parse(script):
    f = StringIO.StringIO(script)
    while pack.remaining(f):
        opcode_str = f.read(1)
        opcode = ord(opcode_str)
        opcode_name, read_func = opcodes[opcode]
        opcode_arg = read_func(f)
        yield opcode_name, opcode_arg

def get_sigop_count(script):
    weights = {
        'CHECKSIG': 1,
        'CHECKSIGVERIFY': 1,
        'CHECKMULTISIG': 20,
        'CHECKMULTISIGVERIFY': 20,
    }
    return sum(weights.get(opcode_name, 0) for opcode_name, opcode_arg in parse(script))

def create_push_script(datums): # datums can be ints or strs
    res = []
    for datum in datums:
        if isinstance(datum, (int, long)):
            if datum == -1 or 1 <= datum <= 16:
                res.append(chr(datum + 80))
                continue
            negative = datum < 0
            datum = math.natural_to_string(abs(datum))
            if datum and ord(datum[0]) & 128:
                datum = '\x00' + datum
            if negative:
                datum = chr(ord(datum[0]) + 128) + datum[1:]
            datum = datum[::-1]
        if len(datum) < 76:
            res.append(chr(len(datum)))
        elif len(datum) <= 0xff:
            res.append(76)
            res.append(chr(len(datum)))
        elif len(datum) <= 0xffff:
            res.append(77)
            res.append(pack.IntType(16).pack(len(datum)))
        elif len(datum) <= 0xffffffff:
            res.append(78)
            res.append(pack.IntType(32).pack(len(datum)))
        else:
            raise ValueError('string too long')
        res.append(datum)
    return ''.join(res)
