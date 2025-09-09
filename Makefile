.PHONY: help init ws-show ws-new-prod ws-select-dev ws-select-prod \
        plan-dev apply-dev plan-prod apply-prod \
        output-dev output-prod state-list-dev state-list-prod \
        head-bucket-dev head-bucket-prod

# Usage:
#   make init
#   AWS_VAULT_PROFILE=sab make plan-dev
#   AWS_VAULT_PROFILE=sab make apply-dev
#   AWS_VAULT_PROFILE=sab make ws-new-prod
#   AWS_VAULT_PROFILE=sab make plan-prod
#   AWS_VAULT_PROFILE=sab make apply-prod
# If you don't use aws-vault, omit AWS_VAULT_PROFILE and ensure your AWS profile/env is set.

TF_DIR ?= infra/terraform

ifeq ($(AWS_VAULT_PROFILE),)
  TF  := terraform
  AWS := aws
else
  TF  := aws-vault exec $(AWS_VAULT_PROFILE) -- terraform
  AWS := aws-vault exec $(AWS_VAULT_PROFILE) -- aws
endif

help:
	@echo "Targets: init, ws-show, ws-new-prod, ws-select-dev, ws-select-prod"
	@echo "         plan-dev, apply-dev, plan-prod, apply-prod"
	@echo "         output-dev, output-prod, state-list-dev, state-list-prod"
	@echo "         head-bucket-dev, head-bucket-prod"
	@echo "Hint: set AWS_VAULT_PROFILE=sab to run via aws-vault."

# Init
init:
	$(TF) -chdir=$(TF_DIR) init

# Workspaces
ws-show:
	$(TF) -chdir=$(TF_DIR) workspace show

ws-new-prod:
	$(TF) -chdir=$(TF_DIR) workspace new prod || true

ws-select-dev:
	$(TF) -chdir=$(TF_DIR) workspace select default

ws-select-prod:
	$(TF) -chdir=$(TF_DIR) workspace select prod

# Dev
plan-dev: ws-select-dev
	$(TF) -chdir=$(TF_DIR) plan -var-file=envs/dev.tfvars

apply-dev: ws-select-dev
	$(TF) -chdir=$(TF_DIR) apply -var-file=envs/dev.tfvars

output-dev: ws-select-dev
	$(TF) -chdir=$(TF_DIR) output

state-list-dev: ws-select-dev
	$(TF) -chdir=$(TF_DIR) state list

head-bucket-dev:
	$(AWS) s3api head-bucket --bucket swing-alert-bot-dev-state

# Prod
plan-prod: ws-select-prod
	$(TF) -chdir=$(TF_DIR) plan -var-file=envs/prod.tfvars

apply-prod: ws-select-prod
	$(TF) -chdir=$(TF_DIR) apply -var-file=envs/prod.tfvars

output-prod: ws-select-prod
	$(TF) -chdir=$(TF_DIR) output

state-list-prod: ws-select-prod
	$(TF) -chdir=$(TF_DIR) state list

head-bucket-prod:
	$(AWS) s3api head-bucket --bucket swing-alert-bot-prod-state

