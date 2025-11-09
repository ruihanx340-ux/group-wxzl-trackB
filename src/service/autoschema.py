# src/service/autoschema.py
AUTO_TICKET_TOOL = {
  "type": "function",
  "name": "create_ticket_draft",
  "description": "Extract maintenance intent from user text as a ticket draft",
  "parameters": {
    "type": "object",
    "properties": {
      "unit_id": {"type": "string"},
      "category": {"type": "string", "enum": ["plumbing", "electrical", "noise", "hvac", "other"]},
      "priority": {"type": "string", "enum": ["high", "medium", "low"]},
      "summary": {"type": "string"},
      "access_window": {"type": "string"},
      "confidence": {"type": "number"}
    },
    "required": ["unit_id", "category", "priority", "summary", "confidence"]
  }
}

def high_confidence(draft: dict, threshold: float = 0.8) -> bool:
    try:
        return float(draft.get("confidence", 0)) >= threshold
    except Exception:
        return False
