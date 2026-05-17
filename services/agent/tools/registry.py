# These definitions are imported by all three modes.
# OpenAI function-calling schema format — compatible with Pipecat + LiveKit Agents + raw OpenAI.
from pipecat.adapters.schemas.function_schema import FunctionSchema

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check if a date/time slot is available for booking. "
                "Call this BEFORE asking the user to confirm. "
                "Returns available=true/false and a list of alternatives."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format. Resolve relative dates like 'tomorrow' to absolute dates."
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM 24-hour format (e.g. '16:30' for 4:30 PM)."
                    }
                },
                "required": ["date", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Confirm and book an appointment that was previously verified as available. "
                "Call this ONLY after check_availability returned available=true AND the user said yes/confirmed. "
                "Do NOT call this without a prior check_availability for the same date+time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format — same value used in check_availability."
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM 24-hour format — same value used in check_availability."
                    },
                    "name": {
                        "type": "string",
                        "description": "Name of the person booking. Use 'Guest' if not provided."
                    }
                },
                "required": ["date", "time", "name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. Mumbai, Delhi, Bangalore"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_crm",
            "description": "Update a customer record in the CRM with new information",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "Field to update: name | phone | address | email"
                    },
                    "value": {
                        "type": "string",
                        "description": "New value for the field"
                    }
                },
                "required": ["field", "value"]
            }
        }
    }
]

def get_tools_schema() -> list[FunctionSchema]:
    """Convert TOOL_DEFINITIONS to Pipecat FunctionSchema objects."""
    schemas = []
    for t in TOOL_DEFINITIONS:
        f = t["function"]
        schemas.append(FunctionSchema(
            name=f["name"],
            description=f["description"],
            properties=f["parameters"]["properties"],
            required=f["parameters"].get("required", [])
        ))
    return schemas
