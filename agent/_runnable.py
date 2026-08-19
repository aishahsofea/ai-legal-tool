"""`add_node` takes one action, so a sync+async node twin needs `RunnableCallable`.

langgraph exposes no public equivalent: `langchain_core.runnables.RunnableLambda`
takes the pair but doesn't inject `store`, which `recall_node` needs, and
`langgraph.utils.runnable` is a back-compat shim marked for removal. So the
private import stays — here, where a langgraph move breaks one line instead of
every call site in agent/graph.py.
"""
from langgraph._internal._runnable import RunnableCallable

__all__ = ["RunnableCallable"]
