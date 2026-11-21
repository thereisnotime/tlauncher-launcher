FROM debian:stable-slim

# Java that runs TLauncher (21 or 25). Minecraft itself uses the per-version
# runtimes TLauncher downloads into ~/.minecraft/runtime.
ARG JAVA_VERSION=21

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      openjdk-${JAVA_VERSION}-jre \
      ca-certificates \
      libgl1 \
      libglx0 \
      libegl1 \
      libgles2 \
      libglvnd0 \
      libpulse0 \
      fonts-dejavu-core \
      fonts-dejavu-extra \
      x11-xserver-utils \
      curl \
      wget \
      unzip \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 app
USER app
WORKDIR /home/app
