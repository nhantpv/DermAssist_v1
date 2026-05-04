"""VLM client — sends image + clinical context + RAG chunks to a vision
model and returns a validated DiagnosisOutput.

Public API: diagnose(...) -> DiagnosisOutput
            DiagnoseError — raised on hard failures (validation x2, etc.)
"""
from backend.vlm.client import DiagnoseError
from backend.vlm.retry import diagnose

__all__ = ["DiagnoseError", "diagnose"]
