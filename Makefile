# CogniFlow — one command per thing a judge or teammate needs.
PY := .venv/Scripts/python.exe      # on Linux/macOS: .venv/bin/python

.PHONY: install smoke test ingest demo verify live ablation ui scan clean

install:            ## create the venv and install pinned dependencies
	py -3.14 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements-dev.txt

smoke:              ## prove the environment works before trusting anything else
	$(PY) scripts/smoke_test.py

test:               ## full offline suite - no API key, no network, no spend
	$(PY) -m pytest tests/ -q

ingest:             ## build the retrieval index from data/knowledge
	$(PY) scripts/ingest_corpus.py

demo:               ## the prerequisite-redirect demo, with the live event stream
	$(PY) demo.py

verify:             ## the demo, checking its own claims instead of narrating them
	$(PY) demo.py --verify

live:               ## one real call per configured provider (needs an API key)
	$(PY) scripts/live_check.py

scan:               ## enforce AGENTS.md RULE 1 before pushing
	$(PY) scripts/check_contributors.py

clean:
	rm -rf .pytest_cache data/chroma data/*.db .cache/llm_replay

ablation:           ## the three-arm study plus BKT fitting (costs nothing)
	$(PY) scripts/run_ablation.py

ui:                 ## Streamlit UI - watch the demo, or be the student yourself
	$(PY) -m streamlit run ui.py
