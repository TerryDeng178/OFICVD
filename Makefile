# Makefile for OFI+CVD Trading System

.PHONY: help equiv equiv-full test

help:
	@echo "Available targets:"
	@echo "  equiv       - Run light equivalence tests"
	@echo "  equiv-full  - Run full equivalence tests"
	@echo "  test        - Run all tests"

equiv:
	python -m pytest -m "equivalence and not slow" --maxfail=1 --disable-warnings

equiv-full:
	python -m pytest -m equivalence --maxfail=1 --disable-warnings

test:
	python -m pytest

