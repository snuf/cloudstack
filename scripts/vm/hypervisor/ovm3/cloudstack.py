#!/usr/bin/python
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
# REMINDER: Needs to work on 2.4 for 3.2.x
# TODO: Needs cleaning and sanitazation.
#
import logging
import time
import re
import os.path
import paramiko
import subprocess
import socket
import tempfile
import logging
import logging.handlers
import string

from xen.util.xmlrpcclient import ServerProxy
from xmlrpclib import Error
from xen.xend import XendClient
from agent.api.base import Agent
from agent.lib.settings import get_api_version
from agent.lib.config import get_config
from xen.xend import sxp

class CloudStack(Agent):
    """
    Cloudstack plugin for OVM3.2.x./OVM3.3.x
    """

    # exposed services
    def get_services(self, version=None):
        return {
            'call': call,
            'get_vncport': get_vnc_port,
            'exec_domr': exec_domr,
            'check_domr_port': check_domr_port,
            'check_dom0_port': check_dom0_port,
            'check_domr_ssh': check_domr_ssh,
            'check_dom0_ip': check_dom0_ip,
            'check_dom0_storage_health_check': check_dom0_storage_health_check,
            'check_dom0_storage_health': check_dom0_storage_health,
            'ovs_domr_upload_file': ovs_domr_upload_file,
            'ovs_control_interface': ovs_control_interface,
            'ovs_mkdirs': ovs_mkdirs,
            'ovs_check_file': ovs_check_file,
            'ovs_upload_ssh_key': ovs_upload_ssh_key,
            'ovs_upload_file': ovs_upload_file,
            'ovs_dom0_stats': ovs_dom0_stats,
            'ovs_domU_stats': ovs_domU_stats,
            'get_module_version': get_module_version,
            'get_ovs_version': get_ovs_version,
            'ping': ping,
            'get_bridge_type': get_bridge_type,
            'get_vswitch_interface_by_ip': get_vswitch_interface_by_ip,
            'get_vswitch_interface_by_name': get_vswitch_interface_by_name,
            'set_iface_ip': set_iface_ip,
            'check_iface_ip': check_iface_ip,
            'add_vswitch_vlan_bridge': add_vswitch_vlan_bridge,
            'del_vswitch_vlan_bridge': del_vswitch_vlan_bridge,

#            'ovs_hard_partition': ovsSetCpuPinning
        }

    def getName(self):
        return self.__class__.__name__

domrPort = 3922
domrKeyFile = os.path.expanduser("~/.ssh/id_rsa.cloud")
domrRoot = "root"
domrTimeout = 10

""" The logger is here """
def Logger(level=logging.DEBUG):
    logger = logging.getLogger('cloudstack-agent')
    logger.setLevel(level)
    handler = logging.handlers.SysLogHandler(address = '/dev/log')
    logger.addHandler(handler)
    return logger

# which version are we intended for?
def get_module_version():
    return "0.3"

# call test
def call(msg):
    return msg

def call_prog(prog, args):
    cmd = [prog ] + args
    try:
        out = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        return out
    except Exception, e:
        print e

#####
# Openvswitch related
#####
def ovs_vsctl(args):
    return call_prog("ovs-vsctl", [ "-vconsole:off" ] + args)

def get_vswitch_bits(cmd):
    l=[]
    out = ovs_vsctl(cmd).stdout
    for line in out:
        l.append(line.rstrip('\n'))
    return l

def check_iface_ip(iface, ip):
    out = call_prog('ip', [ 'addr', 'show', iface ])
    for line in out.stdout:
        if re.search(ip, line):
            return True
    return False

def set_iface_ip(iface, ip, mask):
    if check_iface_ip(iface, ip):
        return True
    try:
        out = call_prog('ip', ['addr', 'add', "%s/%s" % (ip, mask), 'dev', iface])
        if check_iface_ip(iface, ip):
            return True
    except Exception, e:
        print e
    return False

def get_interface_bridge(name):
    bridge=get_vswitch_bits(['iface-to-br', name])
    if not bridge:
        return name
    else:
        return bridge[0]

def add_vswitch_vlan_bridge(name, bridge, vlan):
    if 'mac' in  get_vswitch_interface_by_name(name):
        return get_vswitch_interface_by_name(name)
    ovs_vsctl(["add-br", name, bridge, vlan])
    return get_vswitch_interface_by_name(name)

def del_vswitch_vlan_bridge(name):
    if get_vswitch_interface_by_name(name):
        ovs_vsctl(["del-br", name]).returncode
    return get_vswitch_interface_by_name(name)

def get_vswitch_interface_by_ip(ip):
    iface={}
    pline=""
    out = call_prog('ip', ['addr', 'show'])
    for line in out.stdout:
        if re.search(ip, line):
            el = string.split(line)
            mac = string.split(pline)
            iface['name']=el[-1]
            iface['mac']=mac[1]
            iface['ip']=ip
            iface['bridge']=get_interface_bridge(iface['name'])
            return iface
        else:
            pline=line

def get_vswitch_interface_by_name(name):
    iface={}
    iface['name'] = name
    out = call_prog('ip', ['addr', 'show', name])
    for line in out.stdout:
        if re.search("^\s+link/ether", line):
            iface['mac']=string.split(line)[1]
        if re.search("^\s+inet", line):
            ip=string.split(line)[1]
            ip,mask=string.split(ip,"/")
            iface['ip']=ip
            iface['mask']=mask
    iface['bridge']=get_interface_bridge(name)
    return iface

def get_bridge_type():
    config = get_config()
    try:
        virtualnetwork = config.get('network', 'virtualnetwork').lower()
    except Exception:
        virtualnetwork = 'linuxbridge'
    return virtualnetwork

#####
# Dom0/DomR and statistics related
#####
def paramikoOpts(con, keyfile=domrKeyFile):
    con.load_system_host_keys()
    con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    privatekeyfile = os.path.expanduser(keyfile)
    key = paramiko.RSAKey.from_private_key_file(privatekeyfile)
    return key

# execute something on domr
def exec_domr(host, cmd, timeout=10, username=domrRoot, port=domrPort, keyfile=domrKeyFile):
    ssh = paramiko.SSHClient()
    pkey = paramikoOpts(ssh, keyfile)
    ssh.connect(host, port, username, pkey=pkey, timeout=timeout)
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(cmd)
    exit_status = ssh_stdout.channel.recv_exit_status()
    ssh.close()
    return { "rc": exit_status,
        "out": ''.join(ssh_stdout.readlines()),
        "err": ''.join(ssh_stderr.readlines()) };

# too bad sftp is missing.... Oh no it isn't it's just wrong in the svm config...
# root@s-1-VM:/var/cache/cloud# grep sftp /etc/ssh/sshd_config
# Subsystem   sftp    /usr/libexec/openssh/sftp-server
# root@s-1-VM:/var/cache/cloud# find / -name sftp-server -type f
# /usr/lib/openssh/sftp-server
#
def domrSftp(host, localfile, remotefile, timeout=10, username=domrRoot, port=domrPort, keyfile=domrKeyFile):
    try:
        paramiko.common.logging.basicConfig(level=paramiko.common.DEBUG)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pkey = paramikoOpts(ssh, keyfile)
        ssh.connect(host, port, username, pkey=pkey, timeout=timeout)
        sftp = ssh.open_sftp()
        # either:
        sftp.put(localfile, remotefile)
        # or:
        # rf = sftp.open(remotefile, 'w')
        # rf.write(content)
        # rf.close()
        sftp.close()
        ssh.close()
    except Exception, e:
        raise e
    return True

def domrScp(host, localfile, remotefile, timeout=10, username=domrRoot, port=domrPort, keyfile=domrKeyFile):
    try:
        target = "%s@%s:%s" % (username, host, remotefile)
        cmd = ['scp', '-P', str(port), '-q', '-o', 'StrictHostKeyChecking=no', '-i', os.path.expanduser(keyfile), localfile, target]
        rc = subprocess.call(cmd, shell=False)
        if rc == 0:
            return True
    except Exception, e:
        raise e
    return False

# check a port on dom0
def check_dom0_port(ip, port=domrPort, timeout=3):
    return check_domr_port(ip, port, timeout=timeout)

# check a port on domr
def check_domr_port(ip, port=domrPort, timeout=3):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
    except:
        return False
    return True

# check ssh
def check_domr_ssh(ip, port=domrPort, timeout=10):
    x = exec_domr(ip, "", port=port, timeout=timeout)
    if (x.get("rc") == 0):
        return True
    return False

def grep(file, string):
    c = 0
    for line in open(file):
        if string in line:
           c = c + 1
    return c

def get_ovs_version():
    path = "/etc/ovs-release"
    return re.findall("[\d\.]+$", open(path).readline())[0]

# fix known bugs....
def ovmCsPatch(version="3.2.1"):
    path = "/etc/xen/scripts"
    netcom = "%s/xen-network-common.sh" % path
    netbr = "%s/linuxbridge/ovs-vlan-bridge" % path
    func = "setup_bridge_port"
    # on 3.3.1 this moved to python2.6, but the restart time is already good
    xendConst = "/usr/lib64/python2.4/site-packages/xen/xend/XendConstants.py"
    xendRtime = "MINIMUM_RESTART_TIME"
    netconf = "/etc/sysconfig/network"
    netzero = "NOZEROCONF"
    version = get_ovs_version()

    # this bug is present from 3.2.1 till 3.3.2
    if grep(netcom, "_%s" % func) == 3 and grep(netbr, "_%s" % func) < 1:
        _replaceInFile(netbr, func, "_%s" % func, True)

    # zeroconf is in the way for local loopback, as it introduces a route
    # on every interface that conflicts with what we want
    if grep(netconf, "%s" % netzero) == 0:
        text_file = open("%s" % netconf, "a")
        text_file.write("%s=no\n" % netzero)
        text_file.close()
    else:
        _replaceInFile(netconf,
            netzero,
            "no",
            False)

    # this is fixed in 3.3.1 and onwards
    if version == "3.2.1":
        if grep(xendConst, "%s = %s" % (xendRtime, 60)) == 1:
            _replaceInFile(xendConst,
                "%s = %s" % (xendRtime, 60),
                "%s = %s" % (xendRtime, 10),
                True)
            ovsRestartXend()

    return True

def _replaceInFile(file, orig, set, full=False):
    replaced = False
    if os.path.isfile(file):
        import fileinput
        for line in fileinput.FileInput(file, inplace=1):
            line = line.rstrip('\n')
            if full == False:
                if re.search("%s=" % orig, line):
                    line = "%s=%s" % (orig, set)
                    replaced = True
            else:
                if re.search(orig, line):
                    line = line.replace(orig, set)
                    replaced = True
            print line
    return replaced

def _ovsIni(setting, change):
    ini = "/etc/ovs-agent/agent.ini"
    return _replaceInFile(ini, setting, change)

# enable/disable ssl for the agent
def ovsAgentSetSsl(state):
    ena = "disable"
    if state and state != "disable" and state.lower() != "false":
        ena = "enable"
    return _ovsIni("ssl", ena)

def ovsAgentSetPort(port):
    return _ovsIni("port", port)

def ovsRestartAgent():
    return restartService("ovs-agent")

def ovsRestartXend():
    return restartService("xend")

# replace with popen
def restartService(service):
    command = ['service', service, 'restart']
    subprocess.call(command, shell=False)
    return True

# sets the control interface and removes the route net entry
def ovs_control_interface(dev, cidr):
    controlRoute = False
    command = ['ip route show'];
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    while True:
        line = p.stdout.readline()
        if line == '' and p.poll() != None:
            break
        if line != '':
            if re.search("%s" % (cidr), line) and not re.search("%s" % (dev), line):
                command = ['ip', 'route', 'del', cidr]
                subprocess.call(command, shell=False)
                print "removed: %s" % (line)
            elif re.search("%s" % (cidr), line) and re.search("%s" % (dev), line):
                controlRoute = True

    if controlRoute == False:
        command = ['ip', 'route', 'add', cidr, 'dev', dev];
        subprocess.call(command, shell=False)

    command = ['ifconfig', dev, 'arp']
    subprocess.call(command, shell=False)
    # because OVM creates this and it breaks stuff if we're rebooted sometimes...
    control = "/etc/sysconfig/network-scripts/ifcfg-%s" % (dev)
    command = ['rm', control]
    subprocess.call(command, shell=False)
    return True

def check_dom0_ip(ip):
    command = ['ip addr show']
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    while True:
        line = p.stdout.readline()
        if line != '':
            if re.search("%s/" % (ip), line):
                return True
        else:
            break
    return False

def check_dom0_storage_health_check(path, script, guid, timeout, interval):
    storagehealth="storagehealth.py"
    path="/opt/cloudstack/bin"
    running = False
    started = False
    c = 0
    log = Logger()
    command = ["pgrep -fl %s | grep -v cloudstack.py" % (storagehealth)]

    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    for x in p.stdout:
        if x:
            log.debug("%s is running %s" % (storagehealth, x.rstrip('\n')))
            running = True
            c = c + 1
    if c < 1:
        started = True
        command = ["%s/%s -g %s -t %d -i %d" % (path, storagehealth, guid, timeout, interval)]
        log.warning("%s started: %s/%s for %s with timeout %d and interval %d"
                    % (storagehealth, path, storagehealth, guid, timeout, interval))
        subprocess.call(command, shell=True, close_fds=True)

    return [running, started]

def check_dom0_storage_health(path, script, guid, timeout):
    response = None
    delay = timeout
    log = Logger()
    command = ["%s/%s -g %s -t %s -s" % (path, script, guid, timeout)]
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    p.wait()
    if p.returncode == 0:
        log.warning("primary storage is accessible for %s" % (guid))
        return True
    else:
        log.warning("primary storage NOT is accessible for %s" % (guid))
        return False

# create a dir if we need it
def ovs_mkdirs(dir, mode=0700):
    if not os.path.exists(dir):
        return os.makedirs(dir, mode)
    return True

# if a file exists, easy
def ovs_check_file(file):
    if os.path.isfile(file):
        return True
    return False

def ovs_upload_file(path, filename, content):
    file = "%s/%s" % (path, filename)
    try:
        ovs_mkdirs(os.path.expanduser(path))
    except Error, v:
        print "path was already there %s" % path

    try:
        text_file = open("%s" % file, "w")
        text_file.write("%s" % content)
        text_file.close()
    except Error, v:
        print "something went wrong creating %s: %s" % (file, v)
        return False
    return True

def ovs_domr_upload_file(domr, path, file, content):
    remotefile = "%s/%s" % (path, file)
    try:
        temp = tempfile.NamedTemporaryFile()
        temp.write(content)
        temp.flush()
        # domrSftp(domr, temp.name, remotefile)
        domrScp(domr, temp.name, remotefile)
        temp.close
    except Exception, e:
        print "problem uploading file %s/%s to %s, %s" % (path, file, domr, e)
        raise e
    return True

# upload keys
def ovs_upload_ssh_key(keyfile, content):
    keydir = os.path.expanduser("~/.ssh")
    return ovs_upload_file(keydir, keyfile, content)

# older python,
def ovs_dom0_stats(bridge):
    stats = {}
    stats['cpu'] = "%s" % (100 - float(os.popen("top -b -n 1 | grep Cpu\(s\): | cut -d% -f4|cut -d, -f2").read()))
    stats['free'] = "%s" % (1048576 * int(os.popen("xm info | grep free_memory | awk '{ print $3 }'").read()))
    stats['total'] = "%s" % (1048576 * int(os.popen("xm info | grep total_memory | awk '{ print $3 }'").read()))
    if get_bridge_type() == "linuxbridge":
        stats['tx'] = os.popen("netstat -in | grep %s | head -1 | awk '{print $4 }'" % bridge).read()
        stats['rx'] = os.popen("netstat -in | grep %s | head -1 | awk '{print $8 }'" % bridge).read()
    #  ovs-ofctl dump-ports virbr0 (local or interface)
    elif get_bridge_type() == "openvswitch":
        stats['tx'] = "0"
        stats['rx'] = "0"
    return stats

def get_vnc_port(domain):
    port = "0"
    if re.search("\w-(\d+-)?\d+-VM", domain):
        server = ServerProxy(XendClient.uri)
        dom = server.xend.domain(domain, 1)
        devices = [child for child in sxp.children(dom)
            if len(child) > 0 and child[0] == "device"]
        vfbs_sxp = map(lambda x: x[1], [device for device in devices
            if device[1][0] == "vfb"])[0]
        loc = [child for child in vfbs_sxp
            if child[0] == "location"][0][1]
        listner, port = loc.split(":")
    else:
        print "no valid domain: %s" % domain
    return port

def get_child_by_name(exp, childname, default=None):
    try:
        return [child for child in sxp.children(exp)
                if child[0] == childname][0][1]
    except:
        return default

def ovs_domU_stats(domain):
    _rd_bytes = 0
    _wr_bytes = 0
    _rd_ops = 0
    _wr_ops = 0
    _tx_bytes = 0
    _rx_bytes = 0
    stats = {}
    server = ServerProxy(XendClient.uri)
    dominfo = server.xend.domain(domain, 1)
    domid = get_child_by_name(dominfo, "domid")

    # vbds
    devs = server.xend.domain.getDeviceSxprs(domain, 'vbd')
    devids = [dev[0] for dev in devs]
    for dev in devids:
        sys_path = "/sys/devices/%s-%s-%s/statistics" % ("vbd", domid, dev)
        _rd_bytes += long(open("%s/rd_sect" % sys_path).readline().strip())
        _wr_bytes += long(open("%s/wr_sect" % sys_path).readline().strip())
        _rd_ops += long(open("%s/rd_req" % sys_path).readline().strip())
        _wr_ops += long(open("%s/wr_req" % sys_path).readline().strip())

    # vifs
    devs = server.xend.domain.getDeviceSxprs(domain, 'vif')
    devids = [dev[0] for dev in devs]
    for dev in devids:
        vif = "vif%s.%s" % (domid, dev)
        sys_path = "/sys/devices/%s-%s-%s/net/%s/statistics" % ("vif", domid, dev, vif)
        _tx_bytes += long(open("%s/tx_bytes" % sys_path).readline().strip())
        _rx_bytes += long(open("%s/rx_bytes" % sys_path).readline().strip())

    epoch = time.time()
    stats['rd_bytes'] = "%s" % (_rd_bytes * 512)
    stats['wr_bytes'] = "%s" % (_wr_bytes * 512)
    stats['rd_ops'] = "%s" % (_rd_ops)
    stats['wr_ops'] = "%s" % (_wr_ops)
    stats['tx_bytes'] = "%s" % (_tx_bytes)
    stats['rx_bytes'] = "%s" % (_rx_bytes)
    stats['cputime'] = "%s" % get_child_by_name(dominfo, "cpu_time")
    stats['uptime'] = "%s" % (epoch - get_child_by_name(dominfo, "start_time"))
    stats['vcpus'] = "%s" % get_child_by_name(dominfo, "online_vcpus")
    return stats

def ping(host, count=3):
    if os.system("ping -c %s %s " % (count, host)) == 0:
        return True
    return False

#####
# Self deploy and integration, not de-integration
# should return False if fails
#
# install us if we are missing in:
# /usr/lib64/python2.x/site-packages/agent/api
# and add our hooks in:
# /usr/lib64/python2.x/site-packages/agent/target/api.py
#####
if __name__ == '__main__':
    from distutils.sysconfig import get_python_lib
    from agent.target.api import MODULES
    from shutil import copyfile
    import inspect, os, hashlib, getopt, sys

    # default vars
    exist = False
    agentpath = "%s/agent" % (get_python_lib(1))
    api = "%s/target/api.py" % (agentpath)
    modpath = "%s/api" % (agentpath)
    ssl = "disable"
    port = 0
    exec_sub = ""
    exec_opts = ""

    # get options
    try:
        opts, args = getopt.getopt(sys.argv[1:], "eosp::",
            [ 'port=', 'ssl=', 'exec=', 'opts='])
    except getopt.GetoptError:
        print "Available Options: --port=<number>, --ssl=<true|false>, --exec=<method>, --opts=<arg1,arg2..>"
        sys.exit()

    for o, a in opts:
        if o in ('-s', '--ssl'):
            ssl = a
        if o in ('-p', '--port'):
            port = int(a)
        if o in ('-e', '--exec'):
            exec_sub = a
        if o in ('-o', '--opts'):
            exec_opts = a

    if exec_sub != "":
        func = "%s(%s)" % (exec_sub, exec_opts)
        print "exec: %s" % (func)
        if exec_opts:
            opts = exec_opts.split(',')
        else:
            opts = ""
        print locals()[exec_sub](*opts)
        sys.exit()

    # check if we're in the modules already
    cs = CloudStack()
    for mod in MODULES:
        if re.search(cs.getName(), "%s" % (mod)):
            exist = True

    # if we're not:
    if not exist:
        if os.path.isfile(api):
            import fileinput
            for line in fileinput.FileInput(api, inplace=1):
                line = line.rstrip('\n')
                if re.search("import common", line):
                    line = "%s, cloudstack" % (line)
                if re.search("MODULES", line):
                    n = cs.getName()
                    line = "%s\n\t%s.%s," % (line, n.lower(), n)
                print line
            print "Api inserted, %s in %s" % (cs.getName(), api)
        else:
            print "Api missing, %s" % (api)
    else:
        print "Api present, %s in %s" % (cs.getName(), api)

    # either way check our version and install if checksum differs
    modfile = "%s/%s.py" % (modpath, cs.getName().lower())
    me = os.path.abspath(__file__)
    if os.path.isfile(modfile):
        if hashlib.md5(open(me).read()).hexdigest() != hashlib.md5(open(modfile).read()).hexdigest():
            print "Module copy, %s" % (modfile)
            copyfile(me, modfile)
        else:
            print "Module correct, %s" % (modfile)
    else:
        print "Module copy, %s" % (modfile)
        copyfile(me, modfile)

    # setup ssl and port
    if ssl:
        ovsAgentSetSsl(ssl)
    if port > 1024:
        ovsAgentSetPort(port)

    # restart either way
    ovmCsPatch()
    ovsRestartAgent()
