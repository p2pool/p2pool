import codecs
import datetime
import os
import sys

from twisted.python import log

class EncodeReplacerPipe(object):
    def __init__(self, inner_file):
        self.inner_file = inner_file
        self.softspace = 0
    def write(self, data):
        if isinstance(data, unicode):
            try:
                data = data.encode(self.inner_file.encoding, 'replace')
            except:
                data = data.encode('ascii', 'replace')
        self.inner_file.write(data)
    def flush(self):
        self.inner_file.flush()

class LogFile(object):
    def __init__(self, filename):
        self.filename = filename
        self.inner_file = None
        self.reopen()
    def reopen(self):
        if self.inner_file is not None:
            self.inner_file.close()
        open(self.filename, 'a').close()
        f = open(self.filename, 'rb')
        f.seek(0, os.SEEK_END)
        length = f.tell()
        if length > 100*1000*1000:
            f.seek(-1000*1000, os.SEEK_END)
            while True:
                if f.read(1) in ('', '\n'):
                    break
            data = f.read()
            f.close()
            f = open(self.filename, 'wb')
            f.write(data)
        f.close()
        self.inner_file = codecs.open(self.filename, 'a', 'utf-8')
    def write(self, data):
        self.inner_file.write(data)
    def flush(self):
        self.inner_file.flush()

class TeePipe(object):
    def __init__(self, outputs):
        self.outputs = outputs
    def write(self, data):
        for output in self.outputs:
            output.write(data)
    def flush(self):
        for output in self.outputs:
            output.flush()

class TimestampingPipe(object):
    def __init__(self, inner_file):
        self.inner_file = inner_file
        self.buf = ''
        self.softspace = 0
    def write(self, data):
        buf = self.buf + data
        lines = buf.split('\n')
        for line in lines[:-1]:
            self.inner_file.write('%s %s\n' % (datetime.datetime.now(), line))
            self.inner_file.flush()
        self.buf = lines[-1]
    def flush(self):
        pass

class AbortPipe(object):
    def __init__(self, inner_file):
        self.inner_file = inner_file
        self.softspace = 0
    def write(self, data):
        try:
            self.inner_file.write(data)
        except:
            sys.stdout = sys.__stdout__
            log.DefaultObserver.stderr = sys.stderr = sys.__stderr__
            raise
    def flush(self):
        self.inner_file.flush()

class PrefixPipe(object):
    def __init__(self, inner_file, prefix):
        self.inner_file = inner_file
        self.prefix = prefix
        self.buf = ''
        self.softspace = 0
    def write(self, data):
        buf = self.buf + data
        lines = buf.split('\n')
        for line in lines[:-1]:
            self.inner_file.write(self.prefix + line + '\n')
            self.inner_file.flush()
        self.buf = lines[-1]
    def flush(self):
        pass
