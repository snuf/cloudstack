package com.cloud.hypervisor.ovm3.resources.helpers;

import org.apache.log4j.Logger;

import com.cloud.hypervisor.ovm3.objects.CloudstackPlugin;
import com.cloud.hypervisor.ovm3.objects.Connection;
import com.cloud.hypervisor.ovm3.objects.Network;
import com.cloud.hypervisor.ovm3.objects.Ovm3ResourceException;

public class Ovm3Network {
    private static final Logger LOGGER = Logger
            .getLogger(Ovm3Network.class);
    private Connection c;
    private Ovm3Configuration config;
    private CloudstackPlugin csp;
    private Network net;
    protected BridgeType _bridgeType;
    protected enum BridgeType {
        LINUXBRIDGE, OPENVSWITCH
    }

    public Ovm3Network(Connection conn, Ovm3Configuration ovm3config) throws Ovm3ResourceException {
        c = conn;
        config = ovm3config;
        csp = new CloudstackPlugin(c);
        net = new Network(c);
        determineBridgeType();
    }
    private void determineBridgeType() throws Ovm3ResourceException {
        if (config.getDom0BridgeType() == null) {
            _bridgeType = BridgeType.valueOf(csp.dom0BridgeType().toUpperCase());
            if (_bridgeType == null) {
                _bridgeType = BridgeType.LINUXBRIDGE;
            }
            config.setDom0BridgeType(_bridgeType.toString());
            LOGGER.debug("Bridge set to " + _bridgeType);
        } else {
            _bridgeType = BridgeType.valueOf(config.getDom0BridgeType().toUpperCase());
            LOGGER.debug("Bridge was already " + _bridgeType);
        }
    }

    public Network.Interface getBridgeByName(String name) throws Ovm3ResourceException {
        System.out.println("bridge: " + _bridgeType);
        switch (_bridgeType) {
            case OPENVSWITCH:
                return csp.getBridgeByName(name);
            case LINUXBRIDGE:
            default:
                return net.getBridgeByName(name);
        }
    }
    public String getBridgeNameByIp(String ip) throws Ovm3ResourceException {
        switch (_bridgeType) {
            case OPENVSWITCH:
                return csp.getVswitchBridgeNameByIp(ip);
            case LINUXBRIDGE:
            default:
                return net.getBridgeByIp(ip).getName();
        }
    }

    public Network.Interface getInterfaceByName(String iface) throws Ovm3ResourceException {
        switch (_bridgeType) {
            case OPENVSWITCH:
                return csp.getBridgeByName(iface);
            case LINUXBRIDGE:
            default:
                return net.getInterfaceByName(iface);
        }
    }

    public boolean startOvsLocalConfig(String iface) throws Ovm3ResourceException {
        return net.startOvsLocalConfig(iface);
    }

    public boolean ovsIpConfig(String controlIface, String type,
            String linkLocalGateway, String linkLocalNetMask) throws Ovm3ResourceException {
        switch (_bridgeType) {
            case OPENVSWITCH:
                csp.setNicIp(controlIface, linkLocalGateway, linkLocalNetMask);
                break;
            case LINUXBRIDGE:
            default:
                net.ovsIpConfig(controlIface, type, linkLocalGateway, linkLocalNetMask);
                break;
        }
        if (controlIface.contentEquals(config.getAgentControlNetworkName())) {
            csp.ovsControlInterface(controlIface,
                    linkLocalNetMask);
        }
        return true;
    }

    public boolean stopOvsVlanBridge(String brName, String netName, int vlan) throws Ovm3ResourceException {
        switch (_bridgeType) {
            case OPENVSWITCH:
                LOGGER.debug("Not implemented for openvswitch, can be though!");
                return csp.delVswitchBridge(brName);
            case LINUXBRIDGE:
            default:
                return net.stopOvsVlanBridge(brName, netName, vlan);
        }
    }
    public boolean startOvsVlanBridge(String brName, String netName,
            Integer vlanId) throws Ovm3ResourceException {
        switch (_bridgeType) {
            case OPENVSWITCH:
                LOGGER.debug("Not implemented for openvswitch, can be though!");
                return csp.addVswitchBridge(brName, netName, vlanId);
            case LINUXBRIDGE:
            default:
                return net.startOvsVlanBridge(brName, netName, vlanId);
        }
    }
}
