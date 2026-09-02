# CogniFlow -- convenience wrapper. The real runner is run.py, which works without
# make (Windows machines usually have no make, including the one this was built on).
PY := python

.PHONY: install smoke test ingest demo verify live check ablation ui space scan gates clean help

help:               ## list the tasks
	@$(PY) run.py

install smoke test ingest demo verify live check ablation ui space scan gates:
	@$(PY) run.py $@

clean:
	rm -rf .pytest_cache build data/chroma data/*.db .cache/llm_replay
