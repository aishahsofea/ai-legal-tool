"""Semantic Memory write path (ADR 0010): background extraction of durable
practitioner facts into the cross-thread `(user_id, "semantic")` store. The read
half is the `recall` node in `agent/nodes/recall.py`.
"""
