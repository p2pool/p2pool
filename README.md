Requirements:
-------------------------
Generic:
* Feathercoin >=0.6.4
* Python
* Twisted
* python-argparse (for Python <=2.6)

Linux:
* sudo apt-get install python-zope.interface python-twisted python-twisted-web
* sudo apt-get install python-argparse # if on Python 2.6 or older

Windows:
* Install Python 2.7: http://www.python.org/getit/
* Install Twisted: http://twistedmatrix.com/trac/wiki/Downloads
* Install Zope.Interface: http://pypi.python.org/pypi/zope.interface/3.8.0
* Install python win32 api: http://sourceforge.net/projects/pywin32/files/pywin32/Build%20218/
* Install python win32 api wmi wrapper: https://pypi.python.org/pypi/WMI/#downloads
* Unzip the files into C:\Python27\Lib\site-packages

Running P2Pool:
-------------------------
To use P2Pool, you must be running your own local bitcoind. For standard
configurations, using P2Pool should be as simple as:

    python run_p2pool.py

Then run your miner program, connecting to 127.0.0.1 on port 9332 with any
username and password.

If you are behind a NAT, you should enable TCP port forwarding on your
router. Forward port 9333 to the host running P2Pool.

Run for additional options.

    python run_p2pool.py --help

Donations towards further development:
-------------------------
    1HNeqi3pJRNvXybNX4FKzZgYJsdTSqJTbk

Official wiki :
-------------------------
https://en.bitcoin.it/wiki/P2Pool

Alternate web front end :
-------------------------
* https://github.com/hardcpp/P2PoolExtendedFrontEnd

Notes for Feathercoin:
=========================
Requirements:
-------------------------
In order to run P2Pool with the Feathercoin network, you would need to build and install the
ltc_scrypt module that includes the scrypt proof of work code that Feathercoin uses for hashes.

Linux:

    cd litecoin_scrypt
    sudo python setup.py install

Windows (mingw):
* Install MinGW: http://www.mingw.org/wiki/Getting_Started
* Install Python 2.7: http://www.python.org/getit/

In bash type this:

    cd litecoin_scrypt
    C:\Python27\python.exe setup.py build --compile=mingw32 install

Windows (microsoft visual c++)
* Open visual studio console

In bash type this:

    SET VS90COMNTOOLS=%VS110COMNTOOLS%	           # For visual c++ 2012
    SET VS90COMNTOOLS=%VS100COMNTOOLS%             # For visual c++ 2010
    cd litecoin_scrypt
    C:\Python27\python.exe setup.py build --compile=mingw32 install
	
If you run into an error with unrecognized command line option '-mno-cygwin', see this:
http://stackoverflow.com/questions/6034390/compiling-with-cython-and-mingw-produces-gcc-error-unrecognized-command-line-o

Running P2Pool for Feathercoin:
-------------------------
Run P2Pool with the "--net feathercoin" option.
Run your miner program, connecting to 127.0.0.1 on port 19327.
Forward port 19339 to the host running P2Pool.

Running P2Pool for CHNcoin:
-------------------------
Run P2Pool with the "--net chncoin" option.
Run your miner program, connecting to 127.0.0.1 on port 8109.
Forward port 8107 to the host running P2Pool.

Donating to skralg:
-------------------------
Feathercoin:
  You can mine on http://ftc.p2pool.skralg.com:19327/ which takes a 1% fee.
  Or you can send your hard-earned Feathercoins to 6hn2ENAgSdBteXj6aXyHuxY28Y6wcz9phV

CHNcoin:
  You can mine on http://chn.p2pool.skralg.com:8109/ which takes a 1% fee.
  Or you can send your hard-earned CHNcoins to CUavsytS7urugUy14gWGyuSK1CF4rJd8Po
