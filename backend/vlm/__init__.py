"""VLM client — sends image + clinical context + RAG chunks to a vision
model and returns a validated DiagnosisOutput.

Public API:
    diagnose(...) -> DiagnosisOutput          (image + structured JSON)
    chat_followup(...) -> ChatResponse        (text-only follow-up)
    DiagnoseError                              (raised on hard failures)
"""
from backend.vlm.chat import ChatResponse, PriorTurn, chat_followup
from backend.vlm.client import DiagnoseError
from backend.vlm.retry import diagnose

__all__ = [
    "ChatResponse",
    "DiagnoseError",
    "PriorTurn",
    "chat_followup",
    "diagnose",
]
