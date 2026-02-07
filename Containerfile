FROM debian:stable-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      openjdk-21-jre \
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
      unzip \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 app
USER app
WORKDIR /home/app
