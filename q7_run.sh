#!/usr/bin/env bash
export PATH=$PATH:/snap/bin

# Retry the NIC mask; the earlier attempt raced with a restart and hit an ETag conflict.
for attempt in 1 2 3; do
  if lxc config device add sandbox eth0 none 2>/dev/null; then break; fi
  lxc config device set sandbox eth0 type=none 2>/dev/null && break
  sleep 3
done
lxc restart sandbox
for i in $(seq 1 60); do
  lxc exec sandbox -- true 2>/dev/null && break
  sleep 2
done

echo "### CONTAINMENT CONFIG ###"
lxc config get sandbox security.privileged
lxc config get sandbox limits.memory
lxc config get sandbox limits.cpu
lxc config device list sandbox
lxc exec sandbox -- ip -o addr show
echo "### host canary present on HOST, absent in container ###"
ls -l /opt/tds-lxd-canary/5730e6a310af.txt
lxc exec sandbox -- ls -la /opt/

echo
echo "### RUNNING PROBE INSIDE CONTAINER ###"
tr -d '\r' < /mnt/c/Users/24f20/Downloads/lxd-sandbox-probe.sh > /root/probe.sh
lxc file push /root/probe.sh sandbox/root/probe.sh
lxc exec sandbox --env HOME=/root -- bash -lc 'cd /root && bash probe.sh' > /root/sandbox.log 2>&1
echo "probe exit=$?"
cp /root/sandbox.log /mnt/c/Users/24f20/Desktop/IITM-Subjects/TDS/ga5/sandbox.log
echo
echo "########## sandbox.log ##########"
cat /root/sandbox.log
