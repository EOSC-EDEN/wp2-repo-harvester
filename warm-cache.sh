#!/bin/sh
# Warm the demo's registry cache before a workshop.
#
# Harvesting a repository the first time costs a re3data lookup and one or two
# FAIRsharing searches, and FAIRsharing is both slow and rate-limited: a search
# that times out leaves that repository's FAIRsharing section missing for the
# next 60 seconds. Visiting each URL once beforehand puts the registry answers
# in the cache, so during the session those harvests make no registry requests
# at all and cannot fail that way.
#
# Run it AFTER any deploy, not before: the cache lives in the service process,
# so a restart empties it.
#
# Completed entries live one hour (RegistryCache.COMPLETED_TTL_SECONDS), so a
# longer session wants a second run partway through - at the break, say.
# Re-running is always safe; a still-cached repository costs nothing.
set -eu

# Where to send the requests.
#
# The default goes through nginx, which rate-limits per client IP (10r/m with a
# burst of 5 - see deploy/eden-harvester.nginx.conf), hence DELAY below. On the
# VM itself you can skip both the rate limit and TLS:
#
#     BASE_URL=http://127.0.0.1:8080 DELAY=0 sh warm-cache.sh
#
# Either way it reaches the same process, so it warms the same cache the public
# is served from.
BASE_URL="${BASE_URL:-https://eden-harvester.vm.fedcloud.eu}"

# Seconds between requests. nginx allows 10 a minute per IP, i.e. one every six
# seconds once the burst of 5 is spent, so anything below ~6 earns a 503 on the
# later URLs. Set DELAY=0 when talking to 127.0.0.1 directly.
DELAY="${DELAY:-7}"

# Workshop participant repositories. The name is only used in the output.
# Add or remove lines as the list changes; blank and #-commented lines are fine.
REPOS=$(cat <<'LIST'
UIST Digital Repository|http://repository.uist.edu.mk/
CROSSDA|https://data.crossda.hr
SWISSUbase|https://www.swissubase.ch/en/
Cave Fauna of Greece Database|https://database.inspee.gr/
EPrints UKLO|https://eprints.uklo.edu.mk
EnergoLocal|https://www.verdava.ro/
POLAR MeteoData Distribution System|https://www.polarmeteoroloji.com/
LIST
)

echo "Warming $BASE_URL (${DELAY}s between requests)"
echo

warmed=0
problems=0
first=yes

# Fed by redirection rather than a pipe: a pipe would run the loop in a
# subshell, and the counters below would be lost when it exited.
while IFS='|' read -r name url; do
    case "$name" in ''|\#*) continue ;; esac
    [ -n "$url" ] || continue

    # Pace before every request but the first, so the last URLs are not refused
    # by our own rate limiter.
    if [ "$first" = no ] && [ "$DELAY" -gt 0 ]; then
        sleep "$DELAY"
    fi
    first=no

    # -G with --data-urlencode builds ?url=... correctly; these URLs contain
    # characters that must not go into a query string raw.
    result=$(curl -sS -o /dev/null \
                  -w '%{http_code} in %{time_total}s  ' \
                  -G --data-urlencode "url=$url" \
                  "$BASE_URL/" 2>&1) || result="request failed: $result"

    case "$result" in
        200\ *)
            printf '  ok        %-38s %s\n' "$name" "$result"
            warmed=$((warmed + 1))
            ;;
        503\ *)
            printf '  BUSY 503  %-38s %s\n' "$name" "$result"
            printf '            ^ rate limited, or every harvest slot busy - raise DELAY\n'
            problems=$((problems + 1))
            ;;
        *)
            printf '  FAILED    %-38s %s\n' "$name" "$result"
            problems=$((problems + 1))
            ;;
    esac
done <<EOF
$REPOS
EOF

echo
echo "$warmed warmed, $problems with problems."
echo
echo "A repeat harvest of any of these should now show a registry phase of"
echo "about a millisecond:"
echo "  journalctl -u eden-harvester -f | grep 'Registry Harvesting'"

# A repository that fails here is not necessarily broken - its landing page may
# simply be unreachable from the VM. Either way that is worth discovering now
# rather than in front of the room.
[ "$problems" -eq 0 ] || exit 1
