# Practice-1-Synthetic-Data-Generation
Practice 1: Synthetic Data Generation 

## Documentation

- [Implementation plan](docs/implementation-plan.md)
- [Original task](task/task.md)

## Local startup

1. Install and start Docker Desktop.
2. Copy `.env.example` to `.env` and set a non-default `POSTGRES_PASSWORD`.
3. Run `docker compose up --build`.
4. Open [http://localhost:8501](http://localhost:8501).

PostgreSQL runs in the `postgres` Docker service. It is stored in the `postgres_data` Docker volume, so PostgreSQL does not need to be installed on the host machine.

## Local UI without Docker

For a host-local Streamlit run, use a project virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The `streamlit` executable is provided by the Python package in
`requirements.txt`; it is not expected to exist on a fresh system Python
installation. Running through `.venv` keeps the project dependencies local and
reproducible.
