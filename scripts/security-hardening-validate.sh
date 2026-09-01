#!/usr/bin/env bash
set -euo pipefail

failed=0
for port in 8080 8180 11434 8140; do
  if ss -ltnH "sport = :${port}" | awk '{print $4}' | grep -Evq '^(127\.0\.0\.1|\[::1\]):'; then
    echo "FAIL port ${port} has a non-loopback listener"
    failed=1
  else
    echo "PASS port ${port} is loopback-only or inactive"
  fi
done

if ss -ltnH 'sport = :8443' | grep -q ':8443'; then
  echo "PASS Caddy TLS listener is present"
else
  echo "FAIL Caddy TLS listener is absent"
  failed=1
fi

if sudo ufw status | grep -q '8443/tcp.*ALLOW'; then
  echo "PASS firewall allows Caddy TLS"
else
  echo "FAIL firewall does not allow Caddy TLS"
  failed=1
fi

exit "${failed}"

