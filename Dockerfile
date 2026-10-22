# syntax=docker/dockerfile:1
ARG DEBIAN_IMAGE=debian:trixie-slim
FROM ${DEBIAN_IMAGE} AS runtime
ARG TARGETARCH
ARG STEAMCMD_SHA256=cebf0046bfd08cf45da6bc094ae47aa39ebf4155e5ede41373b579b8f1071e7c
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

LABEL org.opencontainers.image.title="Project Zomboid" \
      org.opencontainers.image.description="Native x86_64 dedicated server using Valve SteamCMD and the supplied Linux launcher" \
      org.opencontainers.image.licenses="MIT"

COPY --chmod=0755 scripts/security-updates.sh /usr/local/bin/security-updates.sh
COPY security/apt-packages.txt /usr/local/share/project-zomboid/apt-packages.txt
RUN test "${TARGETARCH:-$(dpkg --print-architecture)}" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl lib32gcc-s1 lib32stdc++6 libatomic1 \
       libstdc++6 libsdl2-2.0-0 python3 tini util-linux \
    && /usr/local/bin/security-updates.sh \
    && groupadd --gid 10000 steam \
    && useradd --uid 10000 --gid 10000 --create-home --shell /bin/bash steam \
    && mkdir -p /opt/steamcmd-seed /server /data /run/zomboid \
    && curl --fail --location --silent --show-error --retry 3 \
       https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
       --output /tmp/steamcmd.tar.gz \
    && echo "${STEAMCMD_SHA256}  /tmp/steamcmd.tar.gz" | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/steamcmd.tar.gz --directory /opt/steamcmd-seed \
    && chmod -R a+rX,go-w /opt/steamcmd-seed \
    && if test ! -e /lib/ld-linux.so.2; then ln -s /usr/lib32/ld-linux.so.2 /lib/ld-linux.so.2; fi \
    && rm /tmp/steamcmd.tar.gz \
    && chown -R steam:steam /server /data /run/zomboid /home/steam

ENV HOME=/home/steam LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    SERVER_DIR=/server DATA_DIR=/data RUN_DIR=/run/zomboid \
    STEAMCMD_DIR=/home/steam/steamcmd STEAM_BRANCH=public \
    UPDATE_ON_START=true VALIDATE_ON_UPDATE=true \
    SERVER_NAME=servertest ADMIN_USERNAME=admin \
    MIN_MEMORY=1g MAX_MEMORY=4g GAME_PORT=16261 DIRECT_PORT=16262 \
    SHUTDOWN_TIMEOUT=150

COPY --chmod=0755 scripts/entrypoint.sh scripts/healthcheck.sh scripts/console.sh /usr/local/bin/
COPY --chmod=0755 scripts/configure.py /usr/local/lib/project-zomboid/configure.py
RUN runuser -u steam -- test -x /opt/steamcmd-seed/steamcmd.sh \
    && runuser -u steam -- test -r /usr/local/lib/project-zomboid/configure.py \
    && test -x /lib/ld-linux.so.2
USER 10000:10000
WORKDIR /server
EXPOSE 16261/udp 16262/udp
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30m --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
