FROM quay.io/minio/mc:RELEASE.2022-11-07T23-47-39Z

RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
	install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

ENTRYPOINT ["/bin/bash"]
