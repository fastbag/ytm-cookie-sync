ARG BUILD_FROM
FROM ${BUILD_FROM}

# Chromium for the interactive sign-in, Xvfb + x11vnc + noVNC to show it through ingress
RUN apk add --no-cache \
        python3 \
        py3-cryptography \
        tzdata \
        chromium \
        font-dejavu \
        font-noto \
        xvfb \
        x11vnc \
        novnc \
        su-exec \
    && adduser -D -h /home/chrome -s /sbin/nologin chrome

COPY rootfs/ /
RUN chmod 755 /app/run.sh

CMD [ "/app/run.sh" ]
