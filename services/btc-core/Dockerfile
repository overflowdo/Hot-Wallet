FROM ubuntu:24.04 as builder

WORKDIR /root

ENV BITCOIN_REPO=https://github.com/bitcoin/bitcoin.git
ENV BITCOIN_TAG=v31.0

RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    python3 \
    libevent-dev \
    libboost-dev \
    libsqlite3-dev \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone $BITCOIN_REPO bitcoin

RUN cd bitcoin && \
    git fetch --all --tags --prune && \
    git checkout tags/$BITCOIN_TAG && \
    cmake -B build \
        -DBUILD_TESTS=OFF \
        -DBUILD_BENCH=OFF \
        -DWITH_GUI=OFF \
        -DWITH_ZMQ=OFF \
        -DENABLE_IPC=OFF \
        -DBUILD_BITCOIN_WALLET=ON && \
    cmake --build build -j$(nproc)

RUN strip /root/bitcoin/build/bin/bitcoind && \
    strip /root/bitcoin/build/bin/bitcoin-cli


FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    libevent-2.1-7 \
    libevent-pthreads-2.1-7 \
    libevent-extra-2.1-7 \
    libboost-system1.83.0 \
    libboost-filesystem1.83.0 \
    libboost-thread1.83.0 \
    libsqlite3-0 \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/bitcoin/build/bin/bitcoind /root/
COPY --from=builder /root/bitcoin/build/bin/bitcoin-cli /root/


EXPOSE 18444 18443

ADD src/entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

CMD ["/root/entrypoint.sh"]