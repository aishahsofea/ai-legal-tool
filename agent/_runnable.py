"""Single point of contact with langgraph's private runnable API.

`add_node` takes one action, so registering a sync+async twin needs
`RunnableCallable`. langgraph exposes no public equivalent:
`langchain_core.runnables.RunnableLambda` accepts a sync/async pair but does not
inject `store` from the graph runtime, which `recall_node` depends on, and
`langgraph.utils.runnable` is a back-compat shim its own docstring marks for
removal. Importing from `_internal` directly is the honest option — kept here so
a langgraph upgrade that moves it breaks one line, not nine.
"""
from langgraph._internal._runnable import RunnableCallable

__all__ = ["RunnableCallable"]
