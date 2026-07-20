# port-targets.mk — reusable "free the previous port, then run" pattern.
#
# Include from a project Makefile:   include port-targets.mk
# Override the port(s):              PORTS ?= 8080   (space-separated for many)
# A server `run` target depends on kill-port so restarts never hit
# "address already in use".
#
# ponytail: lsof is the portable default (macOS + most Linux). On a minimal
# Linux image without lsof, swap the `pids=` line for: pids=$$(fuser $$p/tcp 2>/dev/null).

PORTS ?= 8080

.PHONY: kill-port
kill-port:
	@for p in $(PORTS); do \
		pids=$$(lsof -ti tcp:$$p 2>/dev/null || true); \
		if [ -n "$$pids" ]; then \
			echo ">> freeing port $$p (killing: $$pids)"; \
			kill -9 $$pids 2>/dev/null || true; \
		else \
			echo ">> port $$p already free"; \
		fi; \
	done
