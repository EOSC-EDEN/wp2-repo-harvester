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

The VM already serves a stock "Welcome to nginx!" page over valid HTTPS, which means `certbot --nginx` added `listen 443 ssl` to Ubuntu's *existing* default site (`/etc/nginx/sites-enabled/default`) rather than creating a new server block - so that block already has its own `location /` (with `root /var/www/html;`). Check first:

    grep -n "location /" /etc/nginx/sites-enabled/default

nginx refuses two `location /` blocks in one `server{}` with `duplicate location "/"`, so **replace** that existing `location /` with all four `location` blocks from `# Part 2` onwards in `deploy/eden-harvester.nginx.conf` (the exact-match `location = /` and `location = /api/` that carry the rate limit, the prefix `location /` that does not - see the comment in that file for why they're split - and the exact-match `location = /healthz`). Take all four, not just the two rate-limited ones: it is easy to skip `location = /healthz` since it isn't part of the rate-limit story, but it carries `access_log off`, and losing it puts every uptime poll into the access log. `root /var/www/html;` in the replaced block becomes dead code once `/` proxies elsewhere; harmless to leave, but delete it too so nobody goes looking for a static site that no longer serves anything.

Check both edits together with `nginx -t && systemctl reload nginx`.

## Updating

    sh /opt/eden-harvester/deploy.sh

`git config core.fileMode` is `false` in this repository, so the executable bit on `deploy.sh` is not tracked and will not survive a `git clone` on the VM. Running it via `sh` sidesteps that — do not rely on running it directly as `./deploy.sh`.

The checkout is owned by `harvester` (the `chown -R harvester:harvester` step above); `deploy.sh` itself runs as root. Git refuses to pull a repository owned by a different uid ("detected dubious ownership"), so the script pulls as `harvester` via `sudo -u harvester git -C ... pull --ff-only` rather than as root. Only that one step is de-escalated — installing into the venv and restarting the service still need root.

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