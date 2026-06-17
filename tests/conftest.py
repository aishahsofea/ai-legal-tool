import os

# Force the in-process MemorySaver checkpointer for the whole test suite so that
# importing agent.graph never opens a real Postgres connection (DATABASE_URL is
# present in .env and is loaded by node modules at import time).
os.environ.setdefault("CHECKPOINTER", "memory")
