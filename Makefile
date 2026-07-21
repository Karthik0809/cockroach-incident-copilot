.PHONY: help install init seed demo eval test lint fmt ui docker deploy clean

help:
	@echo "install  install dependencies"
	@echo "init     create tables and vector indexes"
	@echo "seed     embed and store the historical incidents"
	@echo "demo     run one full agent incident end to end"
	@echo "eval     measure recall quality"
	@echo "test     run the test suite (no DB or AWS needed)"
	@echo "lint     ruff check + format check"
	@echo "fmt      apply ruff formatting"
	@echo "ui       run the demo UI locally"
	@echo "docker   build the UI image"
	@echo "deploy   deploy the Lambda via SAM"

install:
	pip install -r requirements.txt
	pip install ruff pytest

init:
	python -m scripts.init_db

seed:
	python -m scripts.seed

demo:
	python -m scripts.demo

eval:
	python -m scripts.eval

test:
	pytest

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff format .
	ruff check . --fix

ui:
	streamlit run app/streamlit_app.py

docker:
	docker build -t incident-copilot:local .

deploy:
	sam build -t infra/template.yaml
	sam deploy --guided

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .aws-sam
