from agent.target.api import MODULES

import logging
import time
from agent.api.base import Agent

class Gadget(Agent):
    """ 
    Base class for various Oracle VM Agent modules.
    """
    def get_services(self, version=None):
        """
        Return XML-RPC interfaces exported by this module.
    
        @return: Dict of function name to function mappings.
        @rtype: C{dict}
        """
        raise NotImplementedError()

    """
    Class for OVS to introspect the api
    """
    def get_api_services(self, version=None):
        return {
             'get_api_services': get_api_services
    }

def get_api_services(version=None):
    import inspect
    import pprint
    pp = pprint.PrettyPrinter(indent=4)
    services = {}
    for mod in MODULES:
        services = mod().get_services()
        for name, func in services.items():
            print("%s - %s" % (name, mod))
            info = inspect.getargspec(func)
            for idx,arg in enumerate(info[0]):
                dev = None
                try:
                   dev=info[4][idx]
                except:
                   pass

                print(" argument: %s - default: %s" % (arg, dev))
                
    return services

if __name__ == "__main__":
    get_api_services()
