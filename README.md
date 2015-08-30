Requirements:
-------------------------
Generic:
* Bitcoin >=0.8.5
* Python >=2.6
* Twisted >=10.0.0
* python-argparse (for Python =2.6)

Linux:
* sudo apt-get install python-zope.interface python-twisted python-twisted-web
* sudo apt-get install python-argparse # if on Python 2.6

Windows:
* Install Python 2.7: http://www.python.org/getit/
* Install Twisted: http://twistedmatrix.com/trac/wiki/Downloads
* Install Zope.Interface: http://pypi.python.org/pypi/zope.interface/3.8.0
* Install python win32 api: http://sourceforge.net/projects/pywin32/files/pywin32/Build%20218/
* Install python win32 api wmi wrapper: https://pypi.python.org/pypi/WMI/#downloads
* Unzip the files into C:\Python27\Lib\site-packages

Configuring P2Pool:
-------------------------
This version uses BitPay's API to display payouts in your local currency.
It comes with USD and EUR, if you would like to add more you can do so to the table at the bottom of graphs.html in the web-static directory.



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
    forrestv: 1HNeqi3pJRNvXybNX4FKzZgYJsdTSqJTbk
    hardcpp:  1FBa12SPET7YRGHoTXyawp1EBJyFPzju31
    drazisil: 1CMmcUre9Nhs2ndinA1MDfdhxsSN4Eracq

Official wiki:
-------------------------
https://en.bitcoin.it/wiki/P2Pool

Alternate web frontend:
-------------------------
* Front end included from https://github.com/hardcpp/P2PoolExtendedFrontEnd (with fixes)


Sponsors:
-------------------------

Thanks to:
* The Bitcoin Foundation for its generous support of P2Pool
* The Litecoin Project for its generous donations to P2Pool
* https://github.com/forrestv/p2pool for original work
 
License:
-------------------------

[Available here](COPYING)


