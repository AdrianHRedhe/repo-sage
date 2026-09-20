# Thin wrapper over docker compose whose only real job is making the build
# platform explicit.
#
# This machine exports DOCKER_DEFAULT_PLATFORM=linux/x86_64 globally (see
# ~/.dotfiles/mac/shell/.shell/env.sh). Docker honours that over the daemon
# default, so on an Apple Silicon Mac a plain `docker compose up` built and
# ran the entire app amd64-under-Rosetta. Nothing errored; embedding just
# became slow enough to be indistinguishable from a hang, which is what made
# this so hard to spot. Setting both variables here keeps them in agreement.
#
# Override for an amd64 host: make PLATFORM=linux/amd64 up
PLATFORM ?= linux/arm64
export DOCKER_DEFAULT_PLATFORM = $(PLATFORM)
export REPOSAGE_PLATFORM = $(PLATFORM)

COMPOSE = docker compose

.PHONY: help build up down logs seed shell verify clean tunnel

help:
	@echo "make build   - build the image ($(PLATFORM))"
	@echo "make up      - build if needed, start, wait until healthy"
	@echo "make seed    - clone repos.txt repos and embed them into the data volume"
	@echo "make tunnel  - start the app AND the public cloudflared tunnel"
	@echo "make logs    - follow the app log"
	@echo "make verify  - assert the running image is really $(PLATFORM)"
	@echo "make down    - stop the stack"
	@echo "make clean   - stop the stack and delete the data volume"

build:
	$(COMPOSE) build

# --wait blocks until the healthcheck passes, so this returning means the
# embedding model is loaded and questions can actually be answered.
up:
	$(COMPOSE) up -d --wait reposage-web
	@$(MAKE) --no-print-directory verify

# Seeds the named volume. Safe to re-run: embed skips chunks whose content
# and lineage are unchanged.
#
# The app is stopped first on purpose. Seeding runs in its own container, so
# a running app contributes nothing but ~3GB of resident model - and the two
# together overflowed the Docker VM and got the seeder killed by the *global*
# OOM killer (not the container's own limit), which looks identical to a
# crash for no reason. Seeding is rare and this is a single-instance demo, so
# a few seconds of downtime is the right trade.
seed:
	$(COMPOSE) stop reposage-web
	$(COMPOSE) run --rm reposage-web repo-sage sync
	$(COMPOSE) run --rm reposage-web repo-sage embed --all
	@$(MAKE) --no-print-directory up

# `up` deliberately starts only the app, so the default local workflow does
# not publish anything. `tunnel` additionally brings up cloudflared, which
# makes the site reachable on the public hostname in cloudflared/config.yml.
tunnel:
	$(COMPOSE) up -d --wait reposage-web
	$(COMPOSE) up -d cloudflared

logs:
	$(COMPOSE) logs -f reposage-web

shell:
	$(COMPOSE) run --rm --entrypoint sh reposage-web

# The check every previous debugging attempt skipped. An amd64 image here
# means the platform pin was bypassed again and the app will crawl.
verify:
	@arch=$$(docker image inspect repo-sage-reposage-web --format '{{.Architecture}}'); \
	want=$$(echo $(PLATFORM) | cut -d/ -f2); \
	if [ "$$arch" = "$$want" ]; then \
		echo "image architecture: $$arch (expected $$want) OK"; \
	else \
		echo "image architecture: $$arch but expected $$want - platform pin was bypassed"; exit 1; \
	fi

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) down -v
