# Deploying the harvester demo on the EU Node VM

The VM, its hostname and its certificate are  in place. This covers the application only.

Live at <https://eden-harvester.vm.fedcloud.eu>.

## First install

    adduser --system --group --no-create-home --shell /usr/sbin/nologin harvester
    mkdir -p /opt/eden-harvester
    git clone https://github.com/EOSC-EDEN/wp2-repo-harvester.git /opt/eden-harvester
    cd /opt/eden-harvester
    python3 -m venv venv
    venv/bin/pip install .
    chown -R harvester:harvester /opt/eden-harvester

    cp deploy/eden-harvester.env.example /etc/eden-harvester.env
    chown root:harvester /etc/eden-harvester.env
    chmod 0640 /etc/eden-harvester.env

    cp deploy/eden-harvester.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now eden-harvester

`deploy/eden-harvester.nginx.conf` has two parts that go in two different places: pasting the whole file into one place will not start nginx:

    cp deploy/eden-harvester.nginx.conf /etc/nginx/conf.d/eden-harvester-limits.conf

then open that copy and delete everything from `# Part 2` onwards, leaving only the `limit_req_zone` line (plus its comments), since this is only valid at the `http` level, which is where files under `conf.d/` are included.
Then add the `location` blocks (everything from `# Part 2` onwards in `deploy/eden-harvester.nginx.conf`) to the existing TLS server block by hand.

Check both edits together with `nginx -t && systemctl reload nginx`.

## Updating

    sh /opt/eden-harvester/deploy.sh

`git config core.fileMode` is `false` in this repository, so the executable bit on `deploy.sh` is not tracked and will not survive a `git clone` on the VM. Running it via `sh` sidesteps that — do not rely on running it directly as `./deploy.sh`.

## Checking it

    curl -fsS https://eden-harvester.vm.fedcloud.eu/healthz
    journalctl -u eden-harvester -n 50 --no-pager

A healthy service logs no credential errors: the environment check reports only what the configured mode needs.

## Turning FAIRsharing on later

Only do once a response cache keyed on the repository URL is in place, because the 5-second pacing is per process and concurrent visitors would otherwise re-trigger the same lookups into a 429:

1. put the credentials in `/etc/eden-harvester.env`;
2. set `EDEN_ENABLED_REGISTRIES=re3data,fairsharing`;
3. `systemctl restart eden-harvester`.

No code change, no redeployment.

## Two things to be aware of:

- **VM is currentlx set to expire 2026-11-10**
- **The certificate lasts 90 days.** automatic renewal is enabled; confirm it with `certbot renew --dry-run`