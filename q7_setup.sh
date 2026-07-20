#!/usr/bin/env bash
# GA5 Q7 - build a constrained unprivileged LXD container and seed the host canary.
set -x
export PATH=$PATH:/snap/bin

lxd waitready --timeout=180
lxd init --auto --storage-backend=dir

# Host-side canary, deliberately NOT mounted into the container.
mkdir -p /opt/tds-lxd-canary
printf 'TDS_LXD_CANARY_3ea396f39a491a2d98aa7ca622eef23c8be25b48\n' > /opt/tds-lxd-canary/5730e6a310af.txt
chmod 600 /opt/tds-lxd-canary/5730e6a310af.txt

lxc launch ubuntu:24.04 sandbox

# Wait for the container to finish booting.
for i in $(seq 1 60); do
  lxc exec sandbox -- true 2>/dev/null && break
  sleep 2
done

# --- constraints -----------------------------------------------------------
# Unprivileged is the default (security.privileged=false); state it anyway.
lxc config set sandbox security.privileged false
lxc config set sandbox security.nesting false

# Resources: the probe asks for 1536 MB, so cap well below it, and pin one CPU.
lxc config set sandbox limits.memory 512MB
lxc config set sandbox limits.memory.enforce hard
lxc config set sandbox limits.memory.swap false
lxc config set sandbox limits.cpu 1
lxc config set sandbox limits.processes 200

# Network: remove the NIC entirely so egress cannot succeed.
lxc config device remove sandbox eth0 || true

# Filesystem: no host paths are mounted in. Show what devices exist.
lxc config show sandbox
lxc config device list sandbox

lxc restart sandbox
for i in $(seq 1 60); do
  lxc exec sandbox -- true 2>/dev/null && break
  sleep 2
done

echo "=== container view ==="
lxc exec sandbox -- id
lxc exec sandbox -- cat /proc/meminfo | head -2
lxc exec sandbox -- nproc
lxc exec sandbox -- ls /opt || true
lxc exec sandbox -- which python3 curl wget || true
