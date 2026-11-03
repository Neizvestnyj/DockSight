.DEFAULT_GOAL := help
.NOTPARALLEL:
.PHONY: help

# Help prints through Make itself, so suppress its empty-recipe status message.
ifeq ($(filter-out help,$(MAKECMDGOALS)),)
MAKEFLAGS += --silent
endif

# Register each target and append its description to help in declaration order.
define describe
.PHONY: $(strip $(1))
help::
	@$$(info   $(1)$(2))
endef

help::
	@$(info Usage: make <target>)
	@$(info )
	@$(info Setup)

$(eval $(call describe,install          ,Install backend and frontend dependencies))
install:
	uv sync --project backend --locked
	npm --prefix frontend ci

$(eval $(call describe,update-deps      ,Upgrade backend and frontend dependencies))
update-deps:
	uv sync --project backend --upgrade --all-groups
	npm --prefix frontend update --include=dev

$(eval $(call describe,hooks            ,Install Git hooks))
hooks:
	uv run --project backend python scripts/git_hooks.py install

help::
	@$(info )
	@$(info Development)

$(eval $(call describe,backend          ,Start the backend API))
backend:
	uv run --project backend uvicorn docksight.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1

$(eval $(call describe,frontend         ,Start the frontend development server))
frontend:
	npm --prefix frontend run dev

help::
	@$(info )
	@$(info Validation)

$(eval $(call describe,check            ,Run backend and frontend static checks))
check: check-backend check-frontend

$(eval $(call describe,check-backend    ,Run backend static checks))
check-backend:
	uv run --project backend ruff check backend examples scripts
	uv run --project backend ruff format --check backend examples scripts
	uv run --project backend pyright --project backend
	uv run --project backend lint-imports --config backend/pyproject.toml
	uv run --project backend interrogate -c backend/pyproject.toml backend/src backend/tests examples scripts
	uv run --directory backend complexipy src tests ../examples ../scripts --plain --failed

$(eval $(call describe,check-frontend   ,Run frontend static checks))
check-frontend:
	npm --prefix frontend run check

$(eval $(call describe,test             ,Run backend tests and frontend unit tests))
test: test-backend test-frontend

$(eval $(call describe,test-backend     ,Run backend tests and report duplicate fixtures))
test-backend:
	uv run --project backend pytest backend/tests --dup-fixtures

$(eval $(call describe,test-frontend    ,Run frontend unit tests))
test-frontend:
	npm --prefix frontend test

$(eval $(call describe,test-browser     ,Build the frontend and run browser tests))
test-browser: build
	npm --prefix frontend run test:browser

$(eval $(call describe,build            ,Build the frontend))
build:
	npm --prefix frontend run build

$(eval $(call describe,verify           ,Run all hooks and frontend validation including browser tests))
verify:
	uv run --project backend pre-commit run --all-files
	$(MAKE) check-frontend test-frontend test-browser
