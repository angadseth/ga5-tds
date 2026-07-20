#!/usr/bin/env bash
export PATH=$PATH:/snap/bin

# eth0 comes from the default profile, so it cannot be removed directly.
# Masking it with a "none" device on the instance overrides the profile.
lxc config device add sandbox eth0 none
lxc restart sandbox
for i in $(seq 1 60); do
  lxc exec sandbox -- true 2>/dev/null && break
  sleep 2
done

echo "--- instance devices ---"
lxc config device list sandbox
echo "--- interfaces inside container ---"
lxc exec sandbox -- ip -o addr show
echo "--- routes inside container ---"
lxc exec sandbox -- ip route
echo "--- egress attempt (must fail) ---"
lxc exec sandbox -- timeout 10 curl -sS -m 5 https://example.com/ >/dev/null 2>&1
echo "curl exit=$?"
echo "--- host canary must NOT be visible ---"
lxc exec sandbox -- ls -la /opt/
lxc exec sandbox -- cat /opt/tds-lxd-canary/5730e6a310af.txt 2>&1
echo "cat exit=$?"
echo "--- memory limit ---"
lxc exec sandbox -- head -1 /proc/meminfo
