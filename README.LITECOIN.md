Notes for Litecoin:
=========================
Requirements:
-------------------------
In order to run P2Pool with the Litecoin network, you would need to build and install the
ltc_scrypt module that includes the scrypt proof of work code that Litecoin uses for hashes.

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

Running P2Pool:
-------------------------
Run P2Pool with the "--net litecoin" option.
Run your miner program, connecting to 127.0.0.1 on port 9327.
Forward port 9338 to the host running P2Pool.

Litecoin's use of ports 9332 and 9332 conflicts with P2Pool running on
the Bitcoin network. To avoid problems, add these lines to litecoin.conf
and restart litecoind:

    rpcport=10332
    port=10333
