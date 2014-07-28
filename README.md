Requirements & Installation :
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

Running P2Pool :
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

Option Reference :
-------------------------

    usage: run_p2pool.py [-h] [--version]
                         [--net {bitcoin,fastcoin,litecoin,terracoin}] [--testnet]
                         [--debug] [-a ADDRESS] [--datadir DATADIR]
                         [--logfile LOGFILE] [--merged MERGED_URLS]
                         [--give-author DONATION_PERCENTAGE] [--iocp]
                         [--irc-announce] [--no-bugreport] [--p2pool-port PORT]
                         [-n ADDR[:PORT]] [--disable-upnp] [--max-conns CONNS]
                         [--outgoing-conns CONNS] [--disable-advertise]
                         [-w PORT or ADDR:PORT] [-f FEE_PERCENTAGE]
                         [--bitcoind-config-path BITCOIND_CONFIG_PATH]
                         [--bitcoind-address BITCOIND_ADDRESS]
                         [--bitcoind-rpc-port BITCOIND_RPC_PORT]
                         [--bitcoind-rpc-ssl]
                         [--bitcoind-p2p-port BITCOIND_P2P_PORT]
                         [BITCOIND_RPCUSERPASS [BITCOIND_RPCUSERPASS ...]]
    
    optional arguments:
      -h, --help            show this help message and exit
      --version             show program's version number and exit
      --net {bitcoin,fastcoin,litecoin,terracoin}
                            use specified network (default: bitcoin)
      --testnet             use the network's testnet
      --debug               enable debugging mode
      -a ADDRESS, --address ADDRESS
                            generate payouts to this address (default: <address
                            requested from bitcoind>)
      --datadir DATADIR     store data in this directory (default: <directory
                            run_p2pool.py is in>/data)
      --logfile LOGFILE     log to this file (default: data/<NET>/log)
      --merged MERGED_URLS  call getauxblock on this url to get work for merged
                            mining (example:
                            http://ncuser:ncpass@127.0.0.1:10332/)
      --give-author DONATION_PERCENTAGE
                            donate this percentage of work towards the development
                            of p2pool (default: 1.0)
      --iocp                use Windows IOCP API in order to avoid errors due to
                            large number of sockets being open
      --irc-announce        announce any blocks found on
                            irc://irc.freenode.net/#p2pool
      --no-bugreport        disable submitting caught exceptions to the author
      --disable-upnp        don't attempt to use UPnP to forward p2pool's P2P port
                            from the Internet to this computer
      --disable-advertise   don't advertise local IP address as being available
                            for incoming connections. useful for running a dark
                            node, along with multiple -n ADDR's and --outgoing-
                            conns 0
    
    p2pool interface:
      --p2pool-port PORT    use port PORT to listen for connections (forward this
                            port from your router!) (default: bitcoin:9333,
                            fastcoin:23660, litecoin:9338, terracoin:9323)
      -n ADDR[:PORT], --p2pool-node ADDR[:PORT]
                            connect to existing p2pool node at ADDR listening on
                            port PORT (defaults to default p2pool P2P port) in
                            addition to builtin addresses
      --max-conns CONNS     maximum incoming connections (default: 40)
      --outgoing-conns CONNS
                            outgoing connections (default: 6)
    
    worker interface:
      -w PORT or ADDR:PORT, --worker-port PORT or ADDR:PORT
                            listen on PORT on interface with ADDR for RPC
                            connections from miners (default: all interfaces,
                            bitcoin:9332, fastcoin:5150, litecoin:9327,
                            terracoin:9322)
      -f FEE_PERCENTAGE, --fee FEE_PERCENTAGE
                            charge workers mining to their own bitcoin address (by
                            setting their miner's username to a bitcoin address)
                            this percentage fee to mine on your p2pool instance.
                            Amount displayed at http://127.0.0.1:WORKER_PORT/fee
                            (default: 0)
    
    bitcoind interface:
      --bitcoind-config-path BITCOIND_CONFIG_PATH
                            custom configuration file path (when bitcoind -conf
                            option used)
      --bitcoind-address BITCOIND_ADDRESS
                            connect to this address (default: 127.0.0.1)
      --bitcoind-rpc-port BITCOIND_RPC_PORT
                            connect to JSON-RPC interface at this port (default:
                            bitcoin:8332, fastcoin:9527, litecoin:9332,
                            terracoin:13332 <read from bitcoin.conf if password
                            not provided>)
      --bitcoind-rpc-ssl    connect to JSON-RPC interface using SSL
      --bitcoind-p2p-port BITCOIND_P2P_PORT
                            connect to P2P interface at this port (default:
                            bitcoin:8333, fastcoin:9526, litecoin:9333,
                            terracoin:13333 <read from bitcoin.conf if password
                            not provided>)
      BITCOIND_RPCUSERPASS  bitcoind RPC interface username, then password, space-
                            separated (only one being provided will cause the
                            username to default to being empty, and none will
                            cause P2Pool to read them from bitcoin.conf)

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
