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
systemctl --no-pager --lines=10 status eden-harvester

# Prove it is actually serving rather than merely running.
curl -fsS http://127.0.0.1:8080/healthz && echo " - healthz OK"
