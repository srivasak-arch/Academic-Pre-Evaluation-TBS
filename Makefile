# Academic Pre-Evaluation Dashboard — common tasks
.PHONY: install ingest run test clean

install:        ## install dependencies
	pip install -r requirements.txt

ingest:         ## build/rebuild the SQLite database from the synthetic corpus
	python -m src.ingest

run:            ## launch the dashboard (build DB first if missing)
	@test -f data/dashboard.db || python -m src.ingest
	streamlit run app.py

test:           ## run the full test suite
	python -m pytest tests/ -q

clean:          ## remove the generated database
	rm -f data/dashboard.db
