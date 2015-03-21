// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

package com.cloud.hypervisor.ovm3.resources.helpers;

import java.util.List;

import javax.naming.ConfigurationException;

import org.apache.log4j.Logger;

import com.cloud.agent.api.Answer;
import com.cloud.agent.api.CheckNetworkAnswer;
import com.cloud.agent.api.CheckNetworkCommand;
import com.cloud.agent.api.PingTestCommand;
import com.cloud.agent.api.to.NicTO;
import com.cloud.hypervisor.ovm3.objects.CloudstackPlugin;
import com.cloud.hypervisor.ovm3.objects.Connection;
import com.cloud.hypervisor.ovm3.objects.Ovm3ResourceException;
import com.cloud.network.PhysicalNetworkSetupInfo;
import com.cloud.network.Networks.BroadcastDomainType;
import com.cloud.network.Networks.TrafficType;
import com.cloud.utils.exception.CloudRuntimeException;
import com.cloud.utils.net.NetUtils;

public class Ovm3HypervisorNetwork {
    private static final Logger LOGGER = Logger
            .getLogger(Ovm3HypervisorNetwork.class);
    private Connection c;
    private Ovm3Configuration config;
    public Ovm3HypervisorNetwork(Connection conn, Ovm3Configuration ovm3config) {
        c = conn;
        config = ovm3config;
    }

    public void configureNetworking() throws ConfigurationException {
        try {
           Ovm3Network net = new Ovm3Network(c, config);
           String controlIface = config.getAgentControlNetworkName();
           if (controlIface != null
                   && net.getInterfaceByName(controlIface) == null) {
               LOGGER.debug("starting " + controlIface);
               net.startOvsLocalConfig(controlIface);
               /* ovm replies too "fast" so the bridge can be "busy" */
               int contCount = 0;
               while (net.getInterfaceByName(controlIface) == null) {
                   LOGGER.debug("waiting for " + controlIface);
                   Thread.sleep(1 * 1000);
                   if (contCount > 9) {
                       throw new ConfigurationException("Unable to configure "
                               + controlIface + " on host "
                               + config.getAgentHostname());
                   }
                   contCount++;
               }
           } else {
               LOGGER.debug("already have " + controlIface);
           }
           /* configure the interface */
           net.ovsIpConfig(controlIface, "static",
                   NetUtils.getLinkLocalGateway(),
                   NetUtils.getLinkLocalNetMask());
        } catch (InterruptedException e) {
            LOGGER.error("interrupted?", e);
        } catch (Ovm3ResourceException e) {
            String msg = "Basic configuration failed on " + config.getAgentHostname();
            LOGGER.error(msg, e);
            throw new ConfigurationException(msg + ", " + e.getMessage());
        }
    }

    /**/
    private boolean isNetworkSetupByName(String nameTag) {
        if (nameTag != null) {
            LOGGER.debug("Looking for network setup by name " + nameTag);

            try {
                Ovm3Network net = new Ovm3Network(c, config);
                if (net.getBridgeByName(nameTag) != null) {
                    LOGGER.debug("Found bridge with name: " + nameTag);
                    return true;
                }
            } catch (Ovm3ResourceException e) {
                LOGGER.debug("Unxpected error looking for name: " + nameTag, e);
                return false;
            }
        }
        LOGGER.debug("No bridge with name: " + nameTag);
        return false;
    }

    /* this might have to change in the future, works for now... */
    public CheckNetworkAnswer execute(CheckNetworkCommand cmd) {
        LOGGER.debug("Checking if network name setup is done on "
                    + config.getAgentHostname());

        List<PhysicalNetworkSetupInfo> infoList = cmd
                .getPhysicalNetworkInfoList();
        /* here we assume all networks are set */
        for (PhysicalNetworkSetupInfo info : infoList) {
            if (info.getGuestNetworkName() == null) {
                info.setGuestNetworkName(config.getAgentGuestNetworkName());
            }
            if (info.getPublicNetworkName() == null) {
                info.setPublicNetworkName(config.getAgentPublicNetworkName());
            }
            if (info.getPrivateNetworkName() == null) {
                info.setPrivateNetworkName(config.getAgentPrivateNetworkName());
            }
            if (info.getStorageNetworkName() == null) {
                info.setStorageNetworkName(config.getAgentStorageNetworkName());
            }

            if (!isNetworkSetupByName(info.getGuestNetworkName())) {
                String msg = "Guest Physical Network id:"
                        + info.getPhysicalNetworkId()
                        + ", Guest Network is not configured on the backend by name "
                        + info.getGuestNetworkName();
                LOGGER.error(msg);
                return new CheckNetworkAnswer(cmd, false, msg);
            }
            if (!isNetworkSetupByName(info.getPrivateNetworkName())) {
                String msg = "Private Physical Network id:"
                        + info.getPhysicalNetworkId()
                        + ", Private Network is not configured on the backend by name "
                        + info.getPrivateNetworkName();
                LOGGER.error(msg);
                return new CheckNetworkAnswer(cmd, false, msg);
            }
            if (!isNetworkSetupByName(info.getPublicNetworkName())) {
                String msg = "Public Physical Network id:"
                        + info.getPhysicalNetworkId()
                        + ", Public Network is not configured on the backend by name "
                        + info.getPublicNetworkName();
                LOGGER.error(msg);
                return new CheckNetworkAnswer(cmd, false, msg);
            }
            /* Storage network is optional, will revert to private otherwise */
        }

        return new CheckNetworkAnswer(cmd, true,
                "Network Setup check by names is done");

    }

    public Answer execute(PingTestCommand cmd) {
        try {
            if (cmd.getComputingHostIp() != null) {
                CloudstackPlugin cSp = new CloudstackPlugin(c);
                if (!cSp.ping(cmd.getComputingHostIp())) {
                    return new Answer(cmd, false, "ping failed");
                }
            } else {
                return new Answer(cmd, false, "why asks me to ping a router???");
            }
            return new Answer(cmd, true, "success");
        } catch (Ovm3ResourceException e) {
            LOGGER.debug("Ping " + cmd.getComputingHostIp() + " failed", e);
            return new Answer(cmd, false, e.getMessage());
        }
    }

    private String createVlanBridge(String networkName, Integer vlanId)
            throws Ovm3ResourceException {
        if (vlanId < 1 || vlanId > 4094) {
            String msg = "Incorrect vlan " + vlanId
                    + ", needs to be between 1 and 4094";
            LOGGER.error(msg);
            throw new CloudRuntimeException(msg);
        }
        Ovm3Network net = new Ovm3Network(c, config);
        /* figure out if our bridged vlan exists, if not then create */
        String brName = networkName + "." + vlanId.toString();
        try {
            if (net.getBridgeByName(brName) == null) {
                net.startOvsVlanBridge(brName, networkName, vlanId);
            } else {
                LOGGER.debug("Interface " + brName + " already exists");
            }
        } catch (Ovm3ResourceException e) {
            String msg = "Unable to create vlan " + vlanId.toString()
                    + " bridge for " + networkName;
            LOGGER.warn(msg + ": " + e);
            throw new CloudRuntimeException(msg + ":" + e.getMessage());
        }
        return brName;
    }
    /* getNetwork needs to be split in pure retrieval versus creation */
    public String getNetwork(NicTO nic) throws Ovm3ResourceException {
        String vlanId = null;
        String bridgeName = null;
        BroadcastDomainType bcastType = nic.getBroadcastType();
        TrafficType tType = nic.getType();
        if (bcastType == BroadcastDomainType.Vlan) {
            vlanId = BroadcastDomainType.getValue(nic.getBroadcastUri());
        }

        /* only isolation for guests in our case, which might not be "fair" */
        if (tType == TrafficType.Guest) {
            if (bcastType == BroadcastDomainType.Vlan
                    && !"untagged".equalsIgnoreCase(vlanId)) {
                /* This is completely the wrong place for this, we should NEVER
                 * create a network when we're just trying to figure out if it's there
                 * The name of this is misleading and wrong.
                 */
                bridgeName = createVlanBridge(config.getAgentGuestNetworkName(),
                        Integer.valueOf(vlanId));
            } else if (bcastType == BroadcastDomainType.Lswitch) {
                bridgeName = config.getAgentGuestNetworkName();
            } else {
                // ovs-vsctl add-port virbr0 gre0 -- set interface gre0 type=gre options:remote_ip=192.168.1.67
                bridgeName = config.getAgentGuestNetworkName();
            }

        /* We assume preconfigured interfaces for all other traffic? */
        } else if (tType == TrafficType.Control) {
            bridgeName = config.getAgentControlNetworkName();
        /* perhaps this should join Guest for configurability's sake */
        } else if (tType == TrafficType.Public) {
            bridgeName = config.getAgentPublicNetworkName();
        } else if (tType == TrafficType.Management) {
            bridgeName = config.getAgentPrivateNetworkName();
        } else if (tType == TrafficType.Storage) {
            bridgeName = config.getAgentStorageNetworkName();
        } else {
            throw new CloudRuntimeException("Unknown network traffic type:"
                    + tType);
        }
        return bridgeName;
    }
}
