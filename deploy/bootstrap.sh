#!/bin/bash
set -e

# -y is mandatory: without it dnf waits for confirmation, and in user-data
# there is nobody to confirm — the script hangs forever.
dnf update -y
dnf install -y docker git

# a t3.micro has 1 GB of RAM. The build compiles mysqlclient and Pillow,
# and the OOM killer takes the process down with a cryptic "Killed" and no
# explanation. One gigabyte of swap fixes it.
if [ ! -f /swapfile ]; then
    dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

systemctl enable --now docker
usermod -aG docker ec2-user

PLUGIN_DIR=/usr/local/lib/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"

# the architecture is detected rather than hard-coded: a t3.micro is x86_64
# while a Graviton t4g.micro is aarch64, where an amd64 binary will not run.
# Compose names its assets after uname (x86_64/aarch64), Buildx after Go
# (amd64/arm64) — hence two variables.
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  BX_ARCH=amd64 ;;
    aarch64) BX_ARCH=arm64 ;;
    *) echo "unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

# -f makes curl fail on HTTP errors. Without it a 404 page is saved as the
# "binary" and the plugin silently does not work.
curl -fSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
     -o "$PLUGIN_DIR/docker-compose"
chmod +x "$PLUGIN_DIR/docker-compose"

# Compose needs Buildx >= 0.17 to build images. Buildx has no stable
# "latest/download" asset name, so the version is pinned.
curl -fSL "https://github.com/docker/buildx/releases/download/v0.25.0/buildx-v0.25.0.linux-${BX_ARCH}" \
     -o "$PLUGIN_DIR/docker-buildx"
chmod +x "$PLUGIN_DIR/docker-buildx"

systemctl restart docker

mkdir -p /opt/booking
chown ec2-user:ec2-user /opt/booking

echo "bootstrap done. Now: clone the repo into /opt/booking, create .env, run docker compose up -d --build"
