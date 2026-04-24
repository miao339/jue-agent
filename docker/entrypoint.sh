#!/bin/bash
# Docker/Podman entrypoint: bootstrap config files into the mounted volume, then run jue.
set -e

JUE_HOME="${JUE_HOME:-/opt/data}"
INSTALL_DIR="/opt/jue"

# --- Privilege dropping via gosu ---
# When started as root (the default for Docker, or fakeroot in rootless Podman),
# optionally remap the jue user/group to match host-side ownership, fix volume
# permissions, then re-exec as jue.
if [ "$(id -u)" = "0" ]; then
    if [ -n "$JUE_UID" ] && [ "$JUE_UID" != "$(id -u jue)" ]; then
        echo "Changing jue UID to $JUE_UID"
        usermod -u "$JUE_UID" jue
    fi

    if [ -n "$JUE_GID" ] && [ "$JUE_GID" != "$(id -g jue)" ]; then
        echo "Changing jue GID to $JUE_GID"
        # -o allows non-unique GID (e.g. macOS GID 20 "staff" may already exist
        # as "dialout" in the Debian-based container image)
        groupmod -o -g "$JUE_GID" jue 2>/dev/null || true
    fi

    actual_jue_uid=$(id -u jue)
    if [ "$(stat -c %u "$JUE_HOME" 2>/dev/null)" != "$actual_jue_uid" ]; then
        echo "$JUE_HOME is not owned by $actual_jue_uid, fixing"
        # In rootless Podman the container's "root" is mapped to an unprivileged
        # host UID — chown will fail.  That's fine: the volume is already owned
        # by the mapped user on the host side.
        chown -R jue:jue "$JUE_HOME" 2>/dev/null || \
            echo "Warning: chown failed (rootless container?) — continuing anyway"
    fi

    echo "Dropping root privileges"
    exec gosu jue "$0" "$@"
fi

# --- Running as jue from here ---
source "${INSTALL_DIR}/.venv/bin/activate"

# Create essential directory structure.  Cache and platform directories
# (cache/images, cache/audio, platforms/whatsapp, etc.) are created on
# demand by the application — don't pre-create them here so new installs
# get the consolidated layout from get_jue_dir().
# The "home/" subdirectory is a per-profile HOME for subprocesses (git,
# ssh, gh, npm …).  Without it those tools write to /root which is
# ephemeral and shared across profiles.  See issue #4426.
mkdir -p "$JUE_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# .env
if [ ! -f "$JUE_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$JUE_HOME/.env"
fi

# config.yaml
if [ ! -f "$JUE_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$JUE_HOME/config.yaml"
fi

# SOUL.md
if [ ! -f "$JUE_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$JUE_HOME/SOUL.md"
fi

# Sync bundled skills (manifest-based so user edits are preserved)
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py"
fi

exec jue "$@"
