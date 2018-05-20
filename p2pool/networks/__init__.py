import pkgutil
import importlib

nets = dict((name, importlib.import_module('.'+ name, package="p2pool.networks"))
    for module_loader, name, ispkg in pkgutil.iter_modules(__path__))
for net_name, net in nets.items():
    net.NAME = net_name
