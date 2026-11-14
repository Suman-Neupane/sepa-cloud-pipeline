# Base image: Official Amazon Linux 2023 Minimal
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal

# Allow switching between arm64 (Apple Silicon) and amd64 (GitHub Actions / Intel)
ARG TARGETARCH=arm64

# Map Docker TARGETARCH (arm64 / amd64) to RPM architecture naming (aarch64 / x86_64)
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      RPM_ARCH="aarch64"; \
    else \
      RPM_ARCH="x86_64"; \
    fi && \
    curl -fSL "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator-${RPM_ARCH}.rpm" -o /tmp/aws-emulator.rpm && \
    rpm -i /tmp/aws-emulator.rpm && \
    rm -f /tmp/aws-emulator.rpm && \
    mkdir -p /home/emulator/.aws/emulator && \
    chown -R 1000:1000 /home/emulator

# Security Best Practice: Never run containers as root in production/CI
USER 1000
ENV HOME=/home/emulator

# Official AWS Emulator default HTTPS port
EXPOSE 9297

ENTRYPOINT ["aws-emulator", "-b", "0.0.0.0"]
CMD ["-p", "9297"]
