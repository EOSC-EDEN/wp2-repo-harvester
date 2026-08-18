#!/bin/sh
# Deploy the harvester on the EU Node VM. Run as root on the VM itself.
set -eu

APP_DIR=/opt/eden-harvester

cd "$APP_DIR"
git pull --ff-only
"$APP_DIR/venv/bin/pip" install --upgrade .
systemctl restart eden-harvester
systemctl --no-pager --lines=10 status eden-harvester

# Prove it is actually serving rather than merely running.
curl -fsS http://127.0.0.1:8080/healthz && echo " - healthz OK"
