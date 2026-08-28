# Deploying the harvester demo on the EU Node VM

The VM, its hostname and its certificate are  in place. This covers the application only.

Live at <https://eden-harvester.vm.fedcloud.eu>.

## First install

Commands below are written to be run as root; prefix them with `sudo` otherwise. `nginx -t` in particular needs it - unprivileged it cannot read the letsencrypt key material and fails with `cannot load certificate ... Permission denied`, which looks like a config error but is not one.

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

**What is deployed right now is the `harvester-demo` branch, not `master`** - the clone was `git clone -b harvester-demo ...`, to get the demo running before that branch is merged. `deploy.sh` pulls whatever branch is checked out, so it keeps tracking `harvester-demo` on its own. Once the PR lands, move the checkout over and drop the `-b` from the clone above:

    sudo -u harvester git -C /opt/eden-harvester checkout master
    sh /opt/eden-harvester/deploy.sh

`deploy/eden-harvester.nginx.conf` has two parts that go in two different places: pasting the whole file into one place will not start nginx:

    cp deploy/eden-harvester.nginx.conf /etc/nginx/conf.d/eden-harvester-limits.conf

then delete everything from `# Part 2` onwards in that copy, leaving only the `limit_req_zone` line (plus its comments), since this is only valid at the `http` level, which is where files under `conf.d/` are included:

    sed -i '/^limit_req_zone/q' /etc/nginx/conf.d/eden-harvester-limits.conf

(`q` stops sed after the `limit_req_zone` line, so `-i` truncates the file there.)

The VM already serves a stock "Welcome to nginx!" page over valid HTTPS, which means `certbot --nginx` added `listen 443 ssl` to Ubuntu's *existing* default site (`/etc/nginx/sites-enabled/default`) rather than creating a new server block - so that block already has its own `location /` (with `root /var/www/html;`).

nginx refuses two `location /` blocks in one `server{}` with `duplicate location "/"`, so the four `location` blocks from `# Part 2` onwards in `deploy/eden-harvester.nginx.conf` (the exact-match `location = /` and `location = /api/` that carry the rate limit, the prefix `location /` that does not, and `location = /healthz` - see the comment in that file for why they're split) have to **replace** that existing `location /` rather than sit alongside it.

`sites-enabled/default` is a symlink into `sites-available/`, so edit the target, and do not `sed -i` the symlink path - that would replace the link with a regular file. Back it up and locate the block:

    cp /etc/nginx/sites-available/default /root/default.bak
    grep -n "location\|server_name\|listen" /etc/nginx/sites-available/default

The one to replace is inside the block carrying `server_name eden-harvester.vm.fedcloud.eu` and certbot's `listen 443 ssl`; ignore the commented-out `#location ~ \.php$` and `#location ~ /\.ht`, and the fully commented-out example server block further down. Print the range to get exact line numbers:

    awk 'NR>=40 && NR<=75 {print NR": "$0}' /etc/nginx/sites-available/default

Ubuntu's stock `location /` is five lines ending in `try_files $uri $uri/ =404;` - lines 46-50 as of this writing. Splice the file rather than pasting 50 lines into an editor over SSH: everything before the block, then Part 2 straight from the checkout, then everything after it.

    sed -n '1,45p' /etc/nginx/sites-available/default > /tmp/default.new
    sed -n '/^location = \/ {/,$p' /opt/eden-harvester/deploy/eden-harvester.nginx.conf >> /tmp/default.new
    sed -n '51,$p' /etc/nginx/sites-available/default >> /tmp/default.new
    cp /tmp/default.new /etc/nginx/sites-available/default

Adjust `45` and `51` to whatever the `awk` output shows. `cp` rather than `mv`, so the file keeps its own ownership and permissions.

`root /var/www/html;` (a few lines above the block) becomes dead code once `/` proxies elsewhere; harmless to leave, but delete it too so nobody goes looking for a static site that no longer serves anything. Confirm it is a single uncommented match first:

    grep -n '^\s*root /var/www/html;' /etc/nginx/sites-available/default
    sed -i '/^\s*root \/var\/www\/html;/d' /etc/nginx/sites-available/default

Then review the change and apply it:

    diff /root/default.bak /etc/nginx/sites-available/default
    nginx -t && systemctl reload nginx

The diff should show only those five lines leaving and the four `location` blocks arriving. `cp /root/default.bak /etc/nginx/sites-available/default` restores the original if anything is wrong.

## Updating

    sh /opt/eden-harvester/deploy.sh

`git config core.fileMode` is `false` in this repository, so the executable bit on `deploy.sh` is not tracked and will not survive a `git clone` on the VM. Running it via `sh` sidesteps that — do not rely on running it directly as `./deploy.sh`.

The checkout is owned by `harvester` (the `chown -R harvester:harvester` step above); `deploy.sh` itself runs as root. Git refuses to pull a repository owned by a different uid ("detected dubious ownership"), so the script pulls as `harvester` via `sudo -u harvester git -C ... pull --ff-only` rather than as root. Only that one step is de-escalated — installing into the venv and restarting the service still need root.

## Checking it

    curl -fsS https://eden-harvester.vm.fedcloud.eu/healthz
    journalctl -u eden-harvester -n 50 --no-pager

A healthy service logs no credential errors: the environment check reports only what the configured mode needs.

To confirm the rate limit throttles the harvest entry point and nothing else:

    for i in $(seq 1 10); do curl -o /dev/null -s -w '%{http_code} ' https://eden-harvester.vm.fedcloud.eu/logo-eden.svg; done; echo
    for i in $(seq 1 12); do curl -o /dev/null -s -w '%{http_code} ' https://eden-harvester.vm.fedcloud.eu/; done; echo

Expect ten `200`s for the asset (prefix `location /`, no limit), and for `/` six `200`s then `503`s - the burst of 5 plus the one token 10r/m has issued by then. `503`s on the first line would mean the exact-match blocks are not matching and the prefix block picked up the limit instead. The limit is per client IP and refills on its own, so this costs a minute of throttling from whatever address you test from.

## Turning FAIRsharing on

The response cache this depended on is in place: registry lookups are cached
per repository URL in-process, with one lookup shared between concurrent
visitors, and one FAIRsharing sign-in per process rather than one per harvest.
The pacing constant (`RegistryHTTP.REQUEST_DELAY_SECONDS['fairsharing']`) is
now `7.5`, not `5.0`, and the mechanism changed with it: instead of sleeping
before every request, a per-registry gate waits only until that many seconds
have elapsed since the *previous response returned*. That makes the constant
set the FAIRsharing request rate directly — a hard ceiling of `60 / 7.5` = 8
requests/minute, never more — rather than adding a flat delay on top of
whatever time had already passed, the way the old unconditional sleep did.

1. put the credentials in `/etc/eden-harvester.env`;
2. set `EDEN_ENABLED_REGISTRIES=re3data,fairsharing`;
3. `systemctl restart eden-harvester`.

No code change, no redeployment.

To switch it back off, set `EDEN_ENABLED_REGISTRIES=re3data` and restart. The
page then says FAIRsharing was not consulted because it is switched off in this
deployment, which is a different thing from unavailable.

Watch for rate limiting after any busy session:

    journalctl -u eden-harvester --since today | grep -iE "429|rate.limit|could not be consulted"

Two separate lines cover our own congestion rather than a FAIRsharing limit,
and the grep above catches both: `_try_registry` logs `fairsharing could not
be consulted: another harvest held the FAIRsharing session for more than
60.0s` (from `RepositoryHarvester`), and a distinct WARNING logs `Gave up
waiting <N>s for the FAIRsharing harvester - this is our own request queue,
not a FAIRsharing rate limit` (from `FAIRsharingHarvester._serialized`).
Either one turning up repeatedly is congestion here, not a FAIRsharing limit
- the two are logged differently on purpose.

## Two things to be aware of:

- **VM is currentlx set to expire 2026-11-10**
- **The certificate lasts 90 days.** automatic renewal is enabled; confirm it with `certbot renew --dry-run`