#!/bin/bash
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

echo "####################################################"
echo " Note there is a new systemvm build script based on "
echo " Veewee(Vagrant) under tools/appliance."
echo "####################################################"

set -e
set -x

IMAGENAME=systemvm
LOCATION=/var/lib/images/systemvm
PASSWORD=password
APT_PROXY=
APT_PROXY=http://192.168.1.60:3142/debian
HOSTNAME=systemvm
SIZE=2000
DEBIAN_MIRROR=ftp.us.debian.org/debian
MINIMIZE=true
CLOUDSTACK_RELEASE=4.6.0
offset=4096
arch=amd64
REL=jessie
IMAGE=$LOCATION/$IMAGENAME.img
MOUNTPOINT=/mnt/$IMAGENAME
export JAMMING=""
##
#
##
baseimage() {
    type=$1
    # -debopt \"--variant=minbase\"
    opts="--release $REL --hostname $HOSTNAME --packages /etc/debootstrap/packages-jessie --password $PASSWORD --mirror $APT_PROXY --force"
    if [ "$type" == "ISO" ]
    then
        export JAMMING="true"
        # Add user, hostname and check if second iso device might work, systemvm.iso...

        # grml-debootstrap --target $MOUNTPOINT $opts
        debootstrap --arch amd64  "--variant=minbase" jessie /mnt/systemvm http://192.168.1.60:3142/debian
        sudo mount -o bind /dev $MOUNTPOINT/dev
        sudo mount -o bind /proc $MOUNTPOINT/proc
        chroot $MOUNTPOINT apt-get install -y linux-image-amd64  --no-install-recommends
        bash /etc/debootstrap/scripts/script-jessie
        cp /etc/debootstrap/packages-jessie $MOUNTPOINT/root/
        chroot $MOUNTPOINT apt-get install -y initramfs-tools live-boot live-boot-initramfs-tools `cat /etc/debootstrap/packages-jessie`  --no-install-recommends
        scriptdir="${HOME}/cloudstack/systemvm/patches/debian"
        cd $MOUNTPOINT
        mkdir -p binary/live && mkdir -p binary/isolinux
        rm vmlinux
        rm initrd.img
        ln -s boot/vmlinux-3.16.0-4-amd64 vmlinux
        ln -s boot/initrd.img-3.16.0-4-amd64 initrd.img
        cp vmlinux binary/live/
        cp vmlinuz binary/live/
        cp initrd.img binary/live/
        mksquashfs /mnt/systemvm binary/live/filesystem.squashfs -comp xz -e boot
        cp /usr/lib/syslinux/isolinux.bin binary/isolinux/.
        cp /usr/lib/syslinux/menu.c32 binary/isolinux/.
        cat > binary/isolinux/isolinux.cfg << EOF
ui menu.c32
prompt 0
menu title Boot Menu
timeout 100

label live-amd64
    menu label ^Live (amd64)
    menu default
    linux /live/vmlinuz
    append initrd=/live/initrd.img boot=live persistence console=ttyS0 root=/dev/hda

label live-amd64-failsafe
    menu label ^Live (amd64 failsafe)
    linux /live/vmlinuz
    append initrd=/live/initrd.img boot=live persistence config memtest noapic noapm nodma nomce nolapic nomodeset nosmp nosplash vga=normal console=ttyS0 root=/dev/hda

endtexta
EOF
        xorriso -as mkisofs -r -J -joliet-long -l -cache-inodes -isohybrid-mbr /usr/lib/syslinux/isohdpfx.bin -partition_offset 16 -A "Debian Live"  -b isolinux/isolinux.bin -c isolinux/boot.cat -no-emul-boot -boot-load-size 4 -boot-info-table -o remaster.iso binary

    else
        opts="$opts --vmfile --vmsize ${SIZE}M --target $IMAGE"
        grml-debootstrap $opts
        sudo kpartx -a $IMAGE
        if [ ! -d $TM ]
        then
            sudo mkdir $TM
        fi
        lod=$(sudo kpartx -l $IMAGE | awk -F: '{print $1}')
        sudo kpartx -a $IMAGE
        sudo mount /dev/mapper/$lod $MOUNTPOINT
        sudo mount -o bind /dev $MOUNTPOINT/dev
        sudo mount -o bind /proc $MOUNTPOINT/proc
        sudo chroot $MOUNTPOINT update-grub
    fi
}

fixapt() {
  cat >> etc/default/locale  << EOF
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
EOF

  cat >> etc/locale.gen  << EOF
en_US.UTF-8 UTF-8
EOF

  DEBIAN_FRONTEND=noninteractive
  DEBIAN_PRIORITY=critical
  export DEBIAN_FRONTEND DEBIAN_PRIORITY 
  chroot . dpkg-reconfigure debconf --frontend=noninteractive
  chroot . apt-get -q -y install locales
}

network() {
  echo "$HOSTNAME" > etc/hostname &&
  cat > etc/hosts << EOF 
127.0.0.1       localhost
# The following lines are desirable for IPv6 capable hosts
::1     localhost ip6-localhost ip6-loopback
fe00::0 ip6-localnet
ff00::0 ip6-mcastprefix
ff02::1 ip6-allnodes
ff02::2 ip6-allrouters
ff02::3 ip6-allhosts
EOF

  cat >> etc/network/interfaces << EOF
auto lo eth0
iface lo inet loopback

# The primary network interface
iface eth0 inet static

EOF
}

vpn_config() {
  cp -r ${scriptdir}/vpn/* ./
}

keyname() {
  sed -i "s/root@\(.*\)$/root@systemvm/g" etc/ssh/ssh_host_*.pub
}


password() {
  chroot . echo "root:$PASSWORD" | chroot . chpasswd
}

apache2() {
   chroot . a2enmod ssl rewrite auth_basic auth_digest
   chroot . a2ensite default-ssl
   cp etc/apache2/sites-available/default etc/apache2/sites-available/default.orig
   cp etc/apache2/sites-available/default-ssl etc/apache2/sites-available/default-ssl.orig
}

services() {
  mkdir -p ./var/www/html
  mkdir -p ./opt/cloud/bin
  mkdir -p ./var/cache/cloud
  mkdir -p ./usr/share/cloud
  mkdir -p ./usr/local/cloud
  mkdir -p ./root/.ssh
  #Fix haproxy directory issue
  mkdir -p ./var/lib/haproxy
  mkdir -p ./etc/apache2/conf.d
  
  /bin/cp -r ${scriptdir}/config/* ./
  chroot . systemctl enable cloud-early-config
  # chroot . systemctl disable xl2tpd
  # chroot . chkconfig --add cloud-early-config
  # chroot . chkconfig cloud-early-config on
  # chroot . chkconfig --add iptables-persistent
  # chroot . chkconfig iptables-persistent off
  # chroot . chkconfig --force --add cloud-passwd-srvr
  # chroot . chkconfig cloud-passwd-srvr off
  # chroot . chkconfig --add cloud
  # chroot . chkconfig cloud off
  # chroot . chkconfig monit off
}

cleanup() {
  type=$1 
  if [ "$MINIMIZE" == "true" ]
  then
    rm -rf var/cache/apt/*
    rm -rf var/lib/apt/*
    rm -rf usr/share/locale/[a-d]*
    rm -rf usr/share/locale/[f-z]*
    rm -rf usr/share/doc/*
    if [ "$type" != "ISO" ]
    then
        size=$(df   $MOUNTPOINT | awk '{print $4}' | grep -v Available)
        dd if=/dev/zero of=$MOUNTPOINT/zeros.img bs=1M count=$((((size-150000)) / 1000))
        rm -f $MOUNTPOINT/zeros.img
    fi
  fi
  sudo umount $MOUNTPOINT/dev
  sudo umount $MOUNTPOINT/proc
  if [ "$type" != "ISO" ]
  then
    sudo umount -l $MOUNTPOINT
    loop=$(sudo losetup -a| grep $IMAGE | awk -F: '{print $1}')
    sleep 5
    set +x
    set +e
    cd $scriptdir
    sudo kpartx -d $loop
    sudo losetup -d $loop
  else
    echo "should place other stuff here"
  fi
}

signature() {
  (cd ${scriptdir}/config;  tar cvf ${MOUNTPOINT}/usr/share/cloud/cloud-scripts.tar *)
  (cd ${scriptdir}/vpn;  tar rvf ${MOUNTPOINT}/usr/share/cloud/cloud-scripts.tar *)
  gzip -c ${MOUNTPOINT}/usr/share/cloud/cloud-scripts.tar  > ${MOUNTPOINT}/usr/share/cloud/cloud-scripts.tgz
  md5sum ${MOUNTPOINT}/usr/share/cloud/cloud-scripts.tgz |awk '{print $1}'  > ${MOUNTPOINT}/var/cache/cloud/cloud-scripts-signature
  echo "Cloudstack Release $CLOUDSTACK_RELEASE $(date)" > ${MOUNTPOINT}/etc/cloudstack-release
}

fix_requirements() {
    apt-get install xorriso live-build syslinux squashfs-tools
}

fix_requirements

mkdir -p $IMAGENAME
mkdir -p $LOCATION
MOUNTPOINT=/mnt/$IMAGENAME
export MNTPOINT=$MOUNTPOINT
scriptdir=$(dirname $PWD/$0)

rm -rf /tmp$IMAGENAME/
mkdir -p /tmp/$IMAGENAME

rm -f $IMAGE
begin=$(date +%s)
echo "*************INSTALLING BASEIMAGE********************"
baseimage "NOISO"

cp $scriptdir/config.dat $MOUNTPOINT/root/
cd $MOUNTPOINT

echo "*************CONFIGURING APT********************"
fixapt  
echo "*************DONE CONFIGURING APT********************"

echo "*************CONFIGURING NETWORK********************"
network
echo "*************DONE CONFIGURING NETWORK********************"

echo "*************INSTALLING PACKAGES********************"
keyname
echo "*************DONE INSTALLING PACKAGES********************"

echo "*************CONFIGURING PASSWORD********************"
password

echo "*************CONFIGURING SERVICES********************"
services

echo "*************CONFIGURING APACHE********************"
apache2

echo "*************CONFIGURING VPN********************"
vpn_config

echo "*************GENERATING SIGNATURE********************"
signature

echo "*************CLEANING UP********************"
cleanup "NOISO"

fin=$(date +%s)
t=$((fin-begin))
echo "Finished building image $IMAGE in $t seconds"

