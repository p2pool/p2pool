# Copyright (c) 2003, The Regents of the University of California,
# through Lawrence Berkeley National Laboratory (subject to receipt of
# any required approvals from the U.S. Dept. of Energy).  All rights
# reserved. 
#
"""Logging"""
ident = "$Id$"
import os, sys

WARN = 1
DEBUG = 2


class ILogger:
    '''Logger interface, by default this class
    will be used and logging calls are no-ops.
    '''
    level = 0
    def __init__(self, msg):
        return
    def warning(self, *args, **kw):
        return
    def debug(self, *args, **kw):
        return
    def error(self, *args, **kw):
        return
    def setLevel(cls, level):
        cls.level = level
    setLevel = classmethod(setLevel)
    
    debugOn = lambda self: self.level >= DEBUG
    warnOn = lambda self: self.level >= WARN
    

class BasicLogger(ILogger):
    last = ''
    
    def __init__(self, msg, out=sys.stdout):
        self.msg, self.out = msg, out

    def warning(self, msg, *args, **kw):
        if self.warnOn() is False: return
        if BasicLogger.last != self.msg:
            BasicLogger.last = self.msg
            print >>self, "---- ", self.msg, " ----"
        print >>self, "    %s  " %self.WARN,
        print >>self, msg %args
    WARN = '[WARN]'
    def debug(self, msg, *args, **kw):
        if self.debugOn() is False: return
        if BasicLogger.last != self.msg:
            BasicLogger.last = self.msg
            print >>self, "---- ", self.msg, " ----"
        print >>self, "    %s  " %self.DEBUG,
        print >>self, msg %args
    DEBUG = '[DEBUG]'
    def error(self, msg, *args, **kw):
        if BasicLogger.last != self.msg:
            BasicLogger.last = self.msg
            print >>self, "---- ", self.msg, " ----"
        print >>self, "    %s  " %self.ERROR,
        print >>self, msg %args
    ERROR = '[ERROR]'

    def write(self, *args):
        '''Write convenience function; writes strings.
        '''
        for s in args: self.out.write(s)
        event = ''.join(*args)


_LoggerClass = BasicLogger

class GridLogger(ILogger):
    def debug(self, msg, *args, **kw):
        kw['component'] = self.msg
        gridLog(event=msg %args, level='DEBUG', **kw)

    def warning(self, msg, *args, **kw):
        kw['component'] = self.msg
        gridLog(event=msg %args, level='WARNING', **kw)

    def error(self, msg, *args, **kw):
        kw['component'] = self.msg
        gridLog(event=msg %args, level='ERROR', **kw)


# 
# Registry of send functions for gridLog
# 
GLRegistry = {}

class GLRecord(dict):
    """Grid Logging Best Practices Record, Distributed Logging Utilities

    The following names are reserved:

    event -- log event name
        Below is EBNF for the event name part of a log message.
            name	= <nodot> ( "." <name> )? 
            nodot	= {RFC3896-chars except "."}

        Suffixes:
            start: Immediately before the first action in a task.
            end: Immediately after the last action in a task (that succeeded).
            error: an error condition that does not correspond to an end event.

    ts -- timestamp
    level -- logging level (see levels below)
    status -- integer status code
    gid -- global grid identifier 
    gid, cgid -- parent/child identifiers
    prog -- program name


    More info: http://www.cedps.net/wiki/index.php/LoggingBestPractices#Python

    reserved -- list of reserved names, 
    omitname -- list of reserved names, output only values ('ts', 'event',)
    levels -- dict of levels and description
    """
    reserved = ('ts', 'event', 'level', 'status', 'gid', 'prog')
    omitname = ()
    levels = dict(FATAL='Component cannot continue, or system is unusable.',
        ALERT='Action must be taken immediately.',
        CRITICAL='Critical conditions (on the system).',
        ERROR='Errors in the component; not errors from elsewhere.',
        WARNING='Problems that are recovered from, usually.',
        NOTICE='Normal but significant condition.',
        INFO='Informational messages that would be useful to a deployer or administrator.',
        DEBUG='Lower level information concerning program logic decisions, internal state, etc.',
        TRACE='Finest granularity, similar to "stepping through" the component or system.',
    )

    def __init__(self, date=None, **kw):
        kw['ts'] = date or self.GLDate()
        kw['gid'] = kw.get('gid') or os.getpid()
        dict.__init__(self, kw)

    def __str__(self):
        """
        """
        from cStringIO import StringIO
        s = StringIO(); n = " "
        reserved = self.reserved; omitname = self.omitname; levels = self.levels

        for k in ( list(filter(lambda i: self.has_key(i), reserved)) + 
            list(filter(lambda i: i not in reserved, self.keys()))
        ):
            v = self[k]
            if k in omitname: 
                s.write( "%s " %self.format[type(v)](v) )
                continue

            if k == reserved[2] and v not in levels:
                pass

            s.write( "%s=%s " %(k, self.format[type(v)](v) ) )

        s.write("\n")
        return s.getvalue()

    class GLDate(str):
        """Grid logging Date Format
        all timestamps should all be in the same time zone (UTC). 
        Grid timestamp value format that is a highly readable variant of the ISO8601 time standard [1]:

	YYYY-MM-DDTHH:MM:SS.SSSSSSZ 

        """
        def __new__(self, args=None):
            """args -- datetime (year, month, day[, hour[, minute[, second[, microsecond[,tzinfo]]]]])
            """
            import datetime
            args = args or datetime.datetime.utcnow()
            l = (args.year, args.month, args.day, args.hour, args.minute, args.second, 
                 args.microsecond, args.tzinfo or 'Z')

            return str.__new__(self, "%04d-%02d-%02dT%02d:%02d:%02d.%06d%s" %l)

    format = { int:str, float:lambda x: "%lf" % x, long:str, str:lambda x:x,
        unicode:str, GLDate:str, }


def gridLog(**kw):
    """Send GLRecord, Distributed Logging Utilities
    If the scheme is passed as a keyword parameter
    the value is expected to be a callable function
    that takes 2 parameters: url, outputStr

    GRIDLOG_ON   -- turn grid logging on
    GRIDLOG_DEST -- provide URL destination
    """
    import os

    if not bool( int(os.environ.get('GRIDLOG_ON', 0)) ):
        return

    url = os.environ.get('GRIDLOG_DEST')
    if url is None: 
        return

    ## NOTE: urlparse problem w/customized schemes 
    try:
        scheme = url[:url.find('://')]
        send = GLRegistry[scheme]
        send( url, str(GLRecord(**kw)), )
    except Exception, ex:
        print >>sys.stderr, "*** gridLog failed -- %s" %(str(kw))


def sendUDP(url, outputStr):
    from socket import socket, AF_INET, SOCK_DGRAM
    idx1 = url.find('://') + 3; idx2 = url.find('/', idx1)
    if idx2 < idx1: idx2 = len(url)
    netloc = url[idx1:idx2]
    host,port = (netloc.split(':')+[80])[0:2]
    socket(AF_INET, SOCK_DGRAM).sendto( outputStr, (host,int(port)), )

def writeToFile(url, outputStr):
    print >> open(url.split('://')[1], 'a+'), outputStr

GLRegistry["gridlog-udp"] = sendUDP
GLRegistry["file"] = writeToFile


def setBasicLogger():
    '''Use Basic Logger. 
    '''
    setLoggerClass(BasicLogger)
    BasicLogger.setLevel(0)

def setGridLogger():
    '''Use GridLogger for all logging events.
    '''
    setLoggerClass(GridLogger)

def setBasicLoggerWARN():
    '''Use Basic Logger.
    '''
    setLoggerClass(BasicLogger)
    BasicLogger.setLevel(WARN)

def setBasicLoggerDEBUG():
    '''Use Basic Logger.
    '''
    setLoggerClass(BasicLogger)
    BasicLogger.setLevel(DEBUG)

def setLoggerClass(loggingClass):
    '''Set Logging Class.
    '''

def setLoggerClass(loggingClass):
    '''Set Logging Class.
    '''
    assert issubclass(loggingClass, ILogger), 'loggingClass must subclass ILogger'
    global _LoggerClass
    _LoggerClass = loggingClass

def setLevel(level=0):
    '''Set Global Logging Level.
    '''
    ILogger.level = level

def getLevel():
    return ILogger.level

def getLogger(msg):
    '''Return instance of Logging class.
    '''
    return _LoggerClass(msg)


