#!/usr/bin/env bash
#
# Re-sync every repo in repos.txt and re-embed it, then report the outcome
# to GitHub so a failure is visible without anyone watching the host.
#
# Meant to be driven by whatever scheduler the deployment host has - cron,
# a systemd timer, or launchd - rather than by a scheduler of its own. See
# README "Keeping the index fresh" for the entries.
#
# It delegates the actual work to `make seed` instead of calling docker
# compose itself. That is deliberate: `make seed` stops the web app before
# seeding (the embedder and a running app together get the seeder killed
# by the Docker VM's OOM killer) and pins the build platform (an inherited
# DOCKER_DEFAULT_PLATFORM otherwise runs the whole stack under emulation,
# where embedding is slow enough to look like a hang). Both are documented
# traps in the Makefile; bypassing make would walk straight back into them.
#
# Exit status is the seed's: 0 if the index was rebuilt, non-zero if not.

set -euo pipefail

# Schedulers run with a minimal PATH - cron typically gives you just
# /usr/bin:/bin - so `docker` and `make` are routinely missing even though
# they work fine in an interactive shell. Append the usual install
# locations rather than making every operator debug this once.
#
# Appended, not prepended: an operator who put a specific make or docker
# earlier in PATH (a version manager, a wrapper script) meant it, and
# quietly running a different binary than the one they tested with is a
# worse failure than not finding one at all.
PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${NIGHTLY_SEED_LOG_DIR:-$REPO_ROOT/logs}"
LOG_FILE="$LOG_DIR/nightly-seed.log"
# ${TMPDIR} carries a trailing slash on macOS, which would otherwise show
# up as a doubled separator in every log line naming the lock.
LOCK_DIR="${TMPDIR:-/tmp}"
LOCK_DIR="${LOCK_DIR%/}/reposage-nightly-seed.lock"

# Characters of log tail to attach to a failure report. workflow_dispatch
# inputs are size-limited, and the useful part of a seed failure is always
# at the end (the traceback or the OOM kill), never the top.
LOG_TAIL_CHARS=4000

log() {
    printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$LOG_FILE"
}

# Only some schedulers can be told to fire at a UTC time. cron on Linux
# honours CRON_TZ and systemd honours an explicit UTC OnCalendar, but
# launchd fires in local time only, which drifts an hour twice a year.
# Setting NIGHTLY_SEED_UTC_HOUR lets those schedulers run this hourly and
# have the script itself decide, which stays correct across DST.
gate_on_utc_hour() {
    [ -n "${NIGHTLY_SEED_UTC_HOUR:-}" ] || return 0
    local want
    want="$(printf '%02d' "$NIGHTLY_SEED_UTC_HOUR")"
    if [ "$(date -u +%H)" != "$want" ]; then
        exit 0
    fi
}

# Resolved from the `origin` remote so a fork or a rename needs no edit
# here. Handles both the https and ssh remote spellings.
detect_repo_slug() {
    local url
    url="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
    url="${url%.git}"
    case "$url" in
        *github.com[:/]*) printf '%s' "${url#*github.com}" | sed 's#^[:/]##' ;;
        *) printf '' ;;
    esac
}

# Tells the Nightly seed report workflow what happened. That workflow
# fails its own run when status is not "success", which is what turns a
# broken seed into a GitHub notification; and its run history is the
# heartbeat the Seed watchdog workflow checks, so a *successful* seed has
# to report too or the watchdog will (correctly) call the host dead.
report_to_github() {
    local status="$1" log_excerpt="$2"
    local repo="${SEED_ALERT_REPO:-$(detect_repo_slug)}"
    local ref="${SEED_ALERT_REF:-main}"
    local token="${SEED_ALERT_TOKEN:-}"

    # Every `return 0` below is deliberate: a report that cannot be sent
    # must not turn a successful seed into a failed script run. The
    # watchdog catches the silence on GitHub's side either way.
    if [ -z "$token" ] || [ -z "$repo" ]; then
        log "WARNING: no SEED_ALERT_TOKEN/repo, so nothing was reported to GitHub."
        log "WARNING: the seed watchdog will treat this run as a missed seed."
        return 0
    fi
    if ! command -v python3 >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
        log "WARNING: python3 and curl are both required to report to GitHub; skipping."
        return 0
    fi

    # Built by python3 rather than string-concatenated: a failure log
    # contains quotes, backslashes and newlines, all of which produce
    # invalid JSON (or a silently truncated report) if pasted in raw.
    local payload
    payload="$(
        SEED_STATUS="$status" SEED_LOG="$log_excerpt" SEED_HOST="$(hostname)" SEED_REF="$ref" \
        python3 -c 'import json, os; print(json.dumps({"ref": os.environ["SEED_REF"], "inputs": {"status": os.environ["SEED_STATUS"], "host": os.environ["SEED_HOST"], "log": os.environ["SEED_LOG"]}}))'
    )"

    local http_code
    http_code="$(
        curl -sS -o /dev/null -w '%{http_code}' -X POST \
            -H "Accept: application/vnd.github+json" \
            -H "Authorization: Bearer $token" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            "https://api.github.com/repos/$repo/actions/workflows/nightly-seed.yml/dispatches" \
            -d "$payload" || true
    )"

    # 204 is the documented success for a workflow dispatch. Anything else
    # is worth shouting about locally, because from GitHub's side an
    # unsent report is indistinguishable from a host that never woke up.
    if [ "$http_code" = "204" ]; then
        log "Reported '$status' to $repo."
    else
        log "WARNING: reporting '$status' to $repo failed with HTTP $http_code."
    fi
}

main() {
    gate_on_utc_hour

    mkdir -p "$LOG_DIR"
    # One run's output per file, with a single generation kept. An
    # append-only log on a nightly job grows without bound, and the tail of
    # the most recent run is the only part anyone ever reads.
    if [ -f "$LOG_FILE" ]; then
        mv "$LOG_FILE" "$LOG_FILE.1"
    fi
    : > "$LOG_FILE"

    # A seed can outlast its interval (a big repo, a slow network), and two
    # at once would have the second one stop the app the first is about to
    # restart. mkdir is the atomic test-and-set that every shell has.
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        log "Another nightly seed is still running ($LOCK_DIR exists) - skipping."
        exit 0
    fi
    trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

    # Credentials for the report live alongside the app's own config. Not
    # fatal if absent: the seed itself needs nothing from here.
    if [ -f "$REPO_ROOT/.env" ]; then
        set -a
        # shellcheck disable=SC1091
        . "$REPO_ROOT/.env"
        set +a
    fi

    log "Starting nightly sync + embed in $REPO_ROOT"

    # `make seed` runs sync, then embed --all, then brings the app back up.
    # PLATFORM passes through from the environment (make declares it with
    # ?=), so an amd64 host schedules this with PLATFORM=linux/amd64.
    if make -C "$REPO_ROOT" seed >>"$LOG_FILE" 2>&1; then
        log "Seed finished successfully."
        report_to_github success ""
        exit 0
    fi

    log "Seed FAILED - see $LOG_FILE"
    report_to_github failure "$(tail -c "$LOG_TAIL_CHARS" "$LOG_FILE")"
    exit 1
}

main "$@"
