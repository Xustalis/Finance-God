"""Isolated continuous-learning worker package.

Keep this module import-free. The API process imports only the explicit
read-only context module, while the worker entrypoint imports its runtime
modules directly. This prevents a worker dependency or syntax failure from
becoming a trading-desk startup dependency.
"""
