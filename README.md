Requirements & Installation:
-------------------------
Generic:
* Bitcoin >=0.8.5
* Python >=2.6
* Twisted >=10.0.0
* python-argparse (for Python =2.6)

Linux:
* sudo apt-get install python-zope.interface python-twisted python-twisted-web
* sudo apt-get install python-argparse # if on Python 2.6
* git clone git@github.com:jramos/p2pool.git
* cd p2pool
* make

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

Web Interface :
-------------------------
* https://github.com/jramos/p2pool-node-status

JSON API :
-------------------------

P2Pool exposes a JSON API to allow retrieving statistics about the node and the global P2Pool network. The endpoints are as follows:

* /rate
* /difficulty
* /users
* /user_stales
* /fee
* /current_payouts
* /patron_sendmany - Gives sendmany outputs for fair donations to P2Pool
* /global_stats
* /local_stats
* /peer_addresses
* /peer\_txpool\_sizes
* /pings
* /peer_versions
* /payout_addr
* /recent_blocks
* /uptime
* /stale_rates
* /web/log
* /web/share/&lt;share-hash&gt;

This fork includes additional endpoints for use with the [p2pool-node-status](https://github.com/jramos/p2pool-node-status) web interface.

* /web/block/&lt;block-hash&gt;
* /web/rawtransaction/&lt;tx-hash&gt;

Official Wiki :
-------------------------
https://en.bitcoin.it/wiki/P2Pool

Litecoin :
-------------------------

For Litecoin instructions, please see the [Litecoin README](README.LITECOIN.md).

Sponsors :
-------------------------

Thanks to:
* The Bitcoin Foundation for its generous support of P2Pool
* The Litecoin Project for its generous donations to P2Pool

Donations :
-------------------------
    Forrest Voight, BTC 1HNeqi3pJRNvXybNX4FKzZgYJsdTSqJTbk
    Justin Ramos, BTC 1Fi7YbpTYjHynUqbh1vwPcAqAqwQzeC1gw
