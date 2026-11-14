# ==============================================================================
# Makefile for SEPA Cloud-Native Event Pipeline (Official AWS Emulator :9297)
# ==============================================================================
EMULATOR_PORT ?= 9297
ARCH := $(shell uname -m)
ifeq ($(ARCH),arm64)
	TARGETARCH := arm64
else
	TARGETARCH := amd64
endif

export AWS_ENDPOINT_URL := https://127.0.0.1:$(EMULATOR_PORT)
export AWS_ACCESS_KEY_ID := test
export AWS_SECRET_ACCESS_KEY := test
export AWS_DEFAULT_REGION := eu-central-1
export AWS_VERIFY_SSL := false
export PYTHONPATH := .

.PHONY: help emulator-build emulator-up emulator-down tf-init tf-apply test-unit test-e2e lint

help: ## Show available automation commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

emulator-build: ## Build the Official AWS Emulator Docker image for your CPU architecture
	docker build --build-arg TARGETARCH=$(TARGETARCH) -t aws-emulator -f docker/emulator.Dockerfile .

emulator-up: ## Start the Official AWS Emulator on https://127.0.0.1:9297
	mkdir -p $(HOME)/.aws/emulator
	docker run -d --name aws-emulator --rm \
		--memory=2g --memory-swap=2g \
		-p 127.0.0.1:$(EMULATOR_PORT):$(EMULATOR_PORT) \
		-v $(HOME)/.aws/emulator:/home/emulator/.aws/emulator \
		aws-emulator -p $(EMULATOR_PORT) -a off

emulator-down: ## Stop the running AWS Emulator container
	docker stop aws-emulator || true

tf-init: ## Initialize Terraform providers
	cd terraform && terraform init

tf-apply: ## Provision S3, SQS, DLQ, DynamoDB, SNS, and IAM on the AWS Emulator
	cd terraform && terraform apply -auto-approve

test-unit: ## Run fast SEPA IBAN, 19% VAT & AML unit tests (no Docker needed)
	pytest tests/test_unit_validator.py -v

test-e2e: ## Run end-to-end AWS Emulator integration & DLQ chaos tests
	pytest tests/test_integration_aws.py -v

lint: ## Run Ruff Python linter & Terraform formatting check
	ruff check src/ tests/
	cd terraform && terraform fmt -check
