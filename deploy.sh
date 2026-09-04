#!/bin/sh
# Deploy the harvester on the EU Node VM. Run as root on the VM itself.
set -eu

APP_DIR=/opt/eden-harvester

# The checkout is owned by the harvester user (see the runbook's chown step),
# and this script runs as root - git refuses to operate on a repository owned
# by a different uid ("detected dubious ownership"). Pull as the owning user
# instead of adding a git exception for root, so root never touches the
# checkout at all. pip install (into the venv) and the restart below still
# need root, so only this one step is de-escalated.
sudo -u harvester git -C "$APP_DIR" pull --ff-only
"$APP_DIR/venv/bin/pip" install --upgrade "$APP_DIR"
systemctl restart eden-harvester

# Prove it is actually serving rather than merely running - but wait for it.
#
# systemctl restart returns once systemd has forked uvicorn, not once uvicorn
# has imported the application and bound its port. Checking straight away
# races that bind and reports "Failed to connect" on a perfectly healthy
# deploy, with `status` alongside it showing an uptime of a few milliseconds.
# Because this script runs under `set -e` and the check is its last command,
# that false alarm also made a successful deploy exit non-zero.
wait_for_healthz() {
    i=0
    while [ "$i" -lt 20 ]; do
        if curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1; then
            return 0
        fi
        i=$((i + 1))
        sleep 1
    done
    return 1
}

if wait_for_healthz; then
    systemctl --no-pager --lines=10 status eden-harvester
    echo "healthz OK - deploy complete"
else
    systemctl --no-pager --lines=30 status eden-harvester
    echo "" >&2
    echo "healthz did not answer within 20s - the service is NOT serving." >&2
    echo "The status above is the place to start; journalctl -u eden-harvester" >&2
    echo "carries the full log." >&2
    exit 1
fi
