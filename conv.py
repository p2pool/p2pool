import struct

def uint32(x):
	return x & 0xffffffffL

def bytereverse(x):
	return uint32(( ((x) << 24) | (((x) << 8) & 0x00ff0000) |
			(((x) >> 8) & 0x0000ff00) | ((x) >> 24) ))

def bufreverse(in_buf):
	out_words = ""
	for i in range(0, len(in_buf), 4):
		word = struct.unpack('@I', in_buf[i:i+4])[0]
		out_words += struct.pack('@I', bytereverse(word))
	return out_words

def wordreverse(in_buf):
	out_words = []
	for i in range(0, len(in_buf), 4):
		out_words.append(in_buf[i:i+4])
	out_words.reverse()
	out_buf = ""
	for word in out_words:
		out_buf += word
	return out_buf

def hexbuf(buf):
	hs = ''
	for i in range(len(buf)):
		hs += "%02x" % ord(buf[i:i+1])
	return hs

def targetstr(t):
	xs = "%064x" % (t)
	x = xs.decode('hex')
	x = bufreverse(x)
	x = wordreverse(x)
	return hexbuf(x)
