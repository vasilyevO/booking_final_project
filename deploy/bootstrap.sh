#!/bin/bash
set -e

# RU: -y обязателен: без него dnf ждёт подтверждения, а в user-data
#     подтверждать некому — скрипт зависает навсегда.
# EN: -y is mandatory: without it dnf waits for confirmation, and in user-data
#     there is nobody to confirm — the script hangs forever.
dnf update -y
dnf install -y docker git

# RU: t3.micro имеет 1 ГБ памяти. Сборка компилирует mysqlclient и Pillow,
#     и OOM killer прибивает процесс с загадочным "Killed" без объяснений.
#     Гигабайт swap это лечит.
# EN: a t3.micro has 1 GB of RAM. The build compiles mysqlclient and Pillow,
#     and the OOM killer takes the process down with a cryptic "Killed" and no
#     explanation. One gigabyte of swap fixes it.
if [ ! -f /swapfile ]; then
    dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

systemctl enable --now docker
usermod -aG docker ec2-user

# RU: в исходном скрипте ставился buildx, но НЕ плагин compose — а потом
#     вызывался docker-compose, которого нет. Скрипт падал на последней строке.
#     Плагин ставится в каталог CLI-плагинов и даёт команду "docker compose".
# EN: the original script installed buildx but NOT the compose plugin, then
#     called docker-compose, which does not exist. It failed on its last line.
#     The plugin goes into the CLI plugins directory and provides "docker compose".
PLUGIN_DIR=/usr/local/lib/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"

# RU: архитектура определяется, а не зашивается: t3.micro это x86_64,
#     а t4g.micro на Graviton — aarch64, и amd64-бинарник там не запустится.
# EN: the architecture is detected rather than hard-coded: a t3.micro is x86_64
#     while a Graviton t4g.micro is aarch64, where an amd64 binary will not run.
ARCH=$(uname -m)
sudo curl -SL "https://github.com/docker/buildx/releases/download/v0.25.0/buildx-v0.25.0.linux-${BX_ARCH}" \
     -o "$PLUGIN_DIR/docker-buildx"
sudo chmod +x "$PLUGIN_DIR/docker-buildx"

systemctl restart docker

mkdir -p /opt/booking
chown ec2-user:ec2-user /opt/booking

echo "bootstrap done. Now: clone the repo into /opt/booking, create .env, run docker compose up -d --build"