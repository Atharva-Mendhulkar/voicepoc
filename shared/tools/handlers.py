# Mock implementations. Replace with real integrations in production.
import asyncio
import random
from datetime import datetime

async def check_availability(date: str, time: str) -> dict:
    await asyncio.sleep(0.3)  # simulate API latency
    available = random.choice([True, True, False])  # 67% available
    slots = ["09:00", "10:30", "14:00", "16:30"] if not available else []
    return {
        "available": available,
        "requested": f"{date} at {time}",
        "alternatives": slots if not available else [],
        "message": f"{'Available' if available else 'Slot taken. Alternatives: ' + ', '.join(slots)}"
    }

async def get_weather(city: str) -> dict:
    await asyncio.sleep(0.2)
    # Mock data — replace with OpenWeatherMap ya koi aur
    weather_data = {
        "Mumbai":    {"temp": 32, "condition": "Humid and partly cloudy", "humidity": 78},
        "Delhi":     {"temp": 38, "condition": "Hot and hazy", "humidity": 45},
        "Bangalore": {"temp": 24, "condition": "Pleasant with light breeze", "humidity": 62},
    }
    data = weather_data.get(city, {"temp": 28, "condition": "Partly cloudy", "humidity": 60})
    return {
        "city": city,
        "temperature_c": data["temp"],
        "condition": data["condition"],
        "humidity_pct": data["humidity"],
        "summary": f"{city}: {data['temp']}°C, {data['condition']}"
    }

async def update_crm(field: str, value: str) -> dict:
    await asyncio.sleep(0.4)  # CRM write latency MockData
    return {
        "success": True,
        "field_updated": field,
        "new_value": value,
        "record_id": f"CRM-{random.randint(10000, 99999)}",
        "timestamp": datetime.utcnow().isoformat(),
        "message": f"Successfully updated {field} to '{value}'"
    }

async def book_appointment(date: str, time: str, name: str = "Guest") -> dict:
    await asyncio.sleep(0.4)
    booking_id = f"BK-{date.replace('-', '')}-{time.replace(':', '')}"
    return {
        "success": True,
        "booking_id": booking_id,
        "confirmed": f"{date} at {time}",
        "name": name,
        "message": f"Appointment booked for {name} on {date} at {time}. Booking ID: {booking_id}"
    }

# Appointment tool — used by all three modes
TOOL_HANDLERS = {
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "get_weather": get_weather,
    "update_crm": update_crm,
}

async def execute_tool(name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    return await handler(**arguments)
