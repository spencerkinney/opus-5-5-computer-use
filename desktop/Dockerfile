# A tiny Linux desktop for computer use: Xvfb + XFCE + xdotool + Firefox + noVNC.
# Same idea as Anthropic's reference image (anthropics/anthropic-quickstarts, computer-use-demo), but smaller.
# https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo
FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99 LANG=C.UTF-8 LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    xfce4 xfce4-terminal dbus-x11 xvfb xdotool imagemagick x11-utils \
    firefox-esr novnc websockify x11vnc ca-certificates fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash user \
 && mkdir -p /etc/firefox/policies \
 && echo '{"policies": {"OverrideFirstRunPage": "", "OverridePostUpdatePage": "", "DontCheckDefaultBrowser": true, "DisableTelemetry": true}}' \
    > /etc/firefox/policies/policies.json

USER user
WORKDIR /home/user
# Make the dock's browser button open Firefox directly.
RUN mkdir -p .config/xfce4 && printf 'WebBrowser=firefox\nTerminalEmulator=xfce4-terminal\n' > .config/xfce4/helpers.rc

# Xvfb draws the screen, XFCE is the desktop, x11vnc + noVNC let you watch at :6080.
CMD set -eu; \
    Xvfb :99 -screen 0 1280x800x24 -nolisten tcp & \
    until xdpyinfo -display :99 >/dev/null 2>&1; do sleep 0.2; done; \
    dbus-run-session -- startxfce4 & \
    x11vnc -display :99 -localhost -forever -shared -nopw -quiet -rfbport 5900 & \
    exec websockify --web=/usr/share/novnc 6080 localhost:5900
