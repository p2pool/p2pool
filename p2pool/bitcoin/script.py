from p2pool.util import math, pack

def reads_nothing(f):
    return '', f
def protoPUSH(length):
    return lambda f: pack.read(f, length)
def protoPUSHDATA(size_len):
    def _(f):
        length_str, f = pack.read(f, size_len)
        length = math.string_to_natural(length_str[::-1].lstrip(chr(0)))
        data, f = pack.read(f, length)
        return data, f
    return _

opcodes = {}
for i in xrange(256):
    opcodes[i] = 'UNK_' + str(i), reads_nothing

opcodes[0] = '0', reads_nothing
for i in xrange(1, 76):
    opcodes[i] = 'PUSH%i' % i, protoPUSH(i)
opcodes[76] = 'PUSHDATA1', protoPUSHDATA(1)
opcodes[77] = 'PUSHDATA2', protoPUSHDATA(2)
opcodes[78] = 'PUSHDATA4', protoPUSHDATA(4)
opcodes[79] = '-1', reads_nothing
for i in xrange(81, 97):
    opcodes[i] = str(i - 80), reads_nothing

opcodes[172] = 'CHECKSIG', reads_nothing
opcodes[173] = 'CHECKSIGVERIFY', reads_nothing
opcodes[174] = 'CHECKMULTISIG', reads_nothing
opcodes[175] = 'CHECKMULTISIGVERIFY', reads_nothing

def parse(script):
    f = script, 0
    while pack.size(f):
        opcode_str, f = pack.read(f, 1)
        opcode = ord(opcode_str)
        opcode_name, read_func = opcodes[opcode]
        opcode_arg, f = read_func(f)
        yield opcode_name, opcode_arg

def get_sigop_count(script):
    weights = {
        'CHECKSIG': 1,
        'CHECKSIGVERIFY': 1,
        'CHECKMULTISIG': 20,
        'CHECKMULTISIGVERIFY': 20,
    }
    return sum(weights.get(opcode_name, 0) for opcode_name, opcode_arg in parse(script))
