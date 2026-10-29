# OpenPath free-container node
# ---------------------------------------------------------------------------
# Everything here runs on a free tier: Render (750 h/month, no card),
# GitHub Codespaces (60 core-hours/month) or any host that can build a
# Dockerfile. The image only installs sing-box and writes a config from the
# environment variables, so there is nothing to edit by hand.
#
#   docker build -t openpath .
#   docker run -e OPENPATH_PRESET=vless-ws -e OPENPATH_UUID=$(uuidgen) -p 443:443 openpath
#
# Render:  New -> Web Service -> Build from this repo -> Dockerfile
#          Environment: OPENPATH_PRESET, OPENPATH_UUID, OPENPATH_PASSWORD ...
#          (`openpath paas render` does all of this for you through the API)

FROM alpine:3.20

RUN apk add --no-cache bash curl jq ca-certificates openssl tzdata \
    && update-ca-certificates

ARG TARGETARCH=amd64
ENV OPENPATH_PRESET=vless-ws \
    OPENPATH_PORT=443 \
    OPENPATH_UUID= \
    OPENPATH_PASSWORD= \
    OPENPATH_METHOD=2022-blake3-chacha20-poly1305 \
    OPENPATH_PATH=/openpath \
    OPENPATH_OBFS_PASSWORD= \
    OPENPATH_NAME=OpenPath \
    OPENPATH_SNI=

WORKDIR /opt/openpath
COPY entrypoint.sh /opt/openpath/entrypoint.sh
RUN chmod +x /opt/openpath/entrypoint.sh

# sing-box is downloaded at start so the image never pins an outdated version
EXPOSE 443 8443 8388

HEALTHCHECK --interval=60s --timeout=10s CMD pgrep -x sing-box > /dev/null || exit 1

CMD ["/opt/openpath/entrypoint.sh"]
