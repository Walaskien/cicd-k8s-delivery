CLUSTER ?= cicd-demo
IMAGE   ?= greeter
TAG     ?= local
FAULT   ?= crash-on-start

VENV := .venv/bin

# kind would otherwise merge itself into ~/.kube/config and switch the
# current context, which is not what you want on a machine with other clusters
export KUBECONFIG := $(CURDIR)/.kubeconfig

.PHONY: venv lint test build kind-up deploy smoke kind-down

venv:
	python3 -m venv .venv
	$(VENV)/pip install -r requirements-dev.txt

lint:
	$(VENV)/ruff check .
	$(VENV)/ruff format --check .
	$(VENV)/yamllint -s .
	docker run --rm -i hadolint/hadolint < Dockerfile
	helm lint chart/greeter --strict
	helm template greeter chart/greeter | \
		docker run --rm -i ghcr.io/yannh/kubeconform:v0.8.0 -strict -summary -

test:
	$(VENV)/pytest -q

build:
	docker build -t $(IMAGE):$(TAG) --build-arg APP_VERSION=$(TAG) .

kind-up:
	kind create cluster --name $(CLUSTER) --config kind/cluster.yaml --kubeconfig $(KUBECONFIG)

deploy: build
	kind load docker-image $(IMAGE):$(TAG) --name $(CLUSTER)
	scripts/deploy.sh $(IMAGE) $(TAG)

smoke:
	scripts/smoke.sh $(TAG)

kind-down:
	kind delete cluster --name $(CLUSTER) --kubeconfig $(KUBECONFIG)
	rm -f $(KUBECONFIG)
