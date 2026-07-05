from fastapi import APIRouter

from app.services.holiday_features import holiday_calendar_catalog


router = APIRouter(prefix="/api/features", tags=["features"])


@router.get("/holiday-calendars")
def list_holiday_calendars():
    return holiday_calendar_catalog()