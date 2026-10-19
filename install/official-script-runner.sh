#!/usr/bin/env bash
set -euo pipefail

# Admin tool for Dev Tools code 9956 (firmware/ui/controller.py) -- runs
# an "official" maintenance script published at github.com/japyscope/scripts
# instead of a local one the owner placed under ~/custom (Dev Tools code
# 9955, same trust level as a shell on the device). This one fetches code
# from the internet and runs it as root, so it is NOT run on bare trust:
# every script is verified against that repo's own SHA256SUMS (fetched in
# the same request) before it's allowed to execute -- same trust model
# install/update.py already uses for the firmware's own OTA updates
# (checksum published alongside the artifact in the same repo). This
# protects against corruption/a MITM over the wire, not against a
# compromised maintainer account pushing a bad script to that repo.

usage() {
  echo "usage: sudo japyscope-run-official-script list" >&2
  echo "       sudo japyscope-run-official-script run SCRIPT_NAME.sh" >&2
  exit 2
}

if [[ $EUID -ne 0 ]]; then usage; fi

REPO_RAW_BASE="https://raw.githubusercontent.com/japyscope/scripts/main/scripts"
cmd=${1:-}

fetch_sums() {
  curl -fsSL --max-time 15 "$REPO_RAW_BASE/SHA256SUMS"
}

case $cmd in
  list)
    # SHA256SUMS lines are "<hash>  <filename>" (sha256sum's own format)
    # -- one script name per line, for the caller
    # (firmware/ui/controller.py) to parse.
    fetch_sums | awk '{print $2}'
    ;;
  run)
    name=${2:-}
    if [[ ! $name =~ ^[A-Za-z0-9_-]+\.sh$ ]]; then usage; fi
    sums=$(fetch_sums)
    expected=$(awk -v n="$name" '$2 == n {print $1}' <<<"$sums")
    if [[ -z $expected ]]; then
      echo "No checksum entry for $name in SHA256SUMS -- refusing to run." >&2
      exit 1
    fi
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL --max-time 30 "$REPO_RAW_BASE/$name" -o "$tmp/$name"
    actual=$(sha256sum "$tmp/$name" | awk '{print $1}')
    if [[ $actual != "$expected" ]]; then
      echo "Checksum mismatch for $name (expected $expected, got $actual) -- refusing to run." >&2
      exit 1
    fi
    chmod +x "$tmp/$name"
    echo "Verified $name ($actual) -- running."
    "$tmp/$name"
    ;;
  *)
    usage
    ;;
esac
