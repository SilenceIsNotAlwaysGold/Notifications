FROM python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e AS build

ARG GRADLE_VERSION=8.9
ARG GRADLE_SHA256=d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab
ARG ANDROID_COMMAND_LINE_TOOLS_VERSION=11076708
ARG ANDROID_COMMAND_LINE_TOOLS_SHA1=d313adb7aedccf6cf0cfca51ec180f0059f5f8f8
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV GRADLE_HOME=/opt/gradle
ENV PATH=${PATH}:${GRADLE_HOME}/bin:${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        curl openjdk-21-jdk-headless unzip \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --location \
        "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
        --output /tmp/gradle.zip \
    && echo "${GRADLE_SHA256}  /tmp/gradle.zip" | sha256sum --check --strict \
    && unzip -q /tmp/gradle.zip -d /opt \
    && mv "/opt/gradle-${GRADLE_VERSION}" ${GRADLE_HOME} \
    && rm /tmp/gradle.zip
RUN mkdir -p ${ANDROID_SDK_ROOT}/cmdline-tools \
    && curl --fail --show-error --location \
        "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_COMMAND_LINE_TOOLS_VERSION}_latest.zip" \
        --output /tmp/android-command-line-tools.zip \
    && echo "${ANDROID_COMMAND_LINE_TOOLS_SHA1}  /tmp/android-command-line-tools.zip" | sha1sum --check --strict \
    && unzip -q /tmp/android-command-line-tools.zip -d /tmp/android-command-line-tools \
    && mv /tmp/android-command-line-tools/cmdline-tools ${ANDROID_SDK_ROOT}/cmdline-tools/latest \
    && rm -rf /tmp/android-command-line-tools /tmp/android-command-line-tools.zip
RUN yes | sdkmanager --licenses >/dev/null \
    && sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"

WORKDIR /workspace
COPY . .
RUN gradle --no-daemon testDebugUnitTest lintDebug assembleDebug

FROM scratch AS artifacts
COPY --from=build /workspace/app/build/outputs/apk/debug/app-debug.apk /zhihe-wecom-sender-debug.apk
COPY --from=build /workspace/app/build/reports/tests/testDebugUnitTest/ /test-report/
