import pkgutil

nets = dict((name, __import__(name, globals(), fromlist="dummy"))
    for module_loader, name, ispkg in pkgutil.iter_modules(__path__))
for net_name, net in nets.iteritems():
    net.NAME = net_name
