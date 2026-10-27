import pytest
from fastapi import HTTPException

from app.schemas.resources import (CategoryInput, EventCategoryCreateInput, EventFormField,
                                  EventFormInput, EventInput, EventStatusInput, TariffInput)
from routers.event_management import TRANSITIONS, _event_dump


def test_event_metadata_validates_dates_and_normalizes_text():
    payload = EventInput(name="  Copa  ", edition_year=2027, venue="  Ambato ",
                        registration_start="2027-01-01", registration_end="2027-02-01",
                        starts_at="2027-03-01T08:00:00", ends_at="2027-03-01T18:00:00")
    data = _event_dump(payload)
    assert data["name"] == "Copa"
    assert data["venue"] == "Ambato"
    assert data["ends_at"] > data["starts_at"]


def test_event_rejects_invalid_date_order():
    payload = EventInput(name="Copa", edition_year=2027,
                         registration_start="2027-02-01", registration_end="2027-01-01")
    with pytest.raises(HTTPException) as error:
        _event_dump(payload)
    assert error.value.status_code == 422


def test_event_rejects_registration_after_event_start():
    payload = EventInput(name="Copa", edition_year=2027,
                         registration_start="2027-04-01", registration_end="2027-04-02",
                         starts_at="2027-03-01T08:00:00")
    with pytest.raises(HTTPException, match="no pueden iniciar después"):
        _event_dump(payload)


def test_event_rejects_registration_close_after_event_start():
    payload = EventInput(name="Copa", edition_year=2027,
                         registration_start="2027-02-01", registration_end="2027-04-02",
                         starts_at="2027-03-01T08:00:00")
    with pytest.raises(HTTPException, match="deben cerrar antes"):
        _event_dump(payload)


def test_event_lifecycle_has_only_explicit_transitions():
    assert "LIVE" in TRANSITIONS["SCHEDULED"]
    assert "FINISHED" in TRANSITIONS["LIVE"]
    assert TRANSITIONS["FINISHED"] == set()
    assert EventStatusInput(status="SCHEDULED").status == "SCHEDULED"
    with pytest.raises(ValueError):
        EventStatusInput(status="MAGIC")


def test_custom_form_contract_limits_and_field_types():
    form = EventFormInput(title="Formulario", fields=[
        EventFormField(id="school", label="Institución", type="dropdown",
                       required=True, options=["UTA", "Otra"])
    ])
    assert form.fields[0].required is True
    with pytest.raises(ValueError):
        EventFormField(id="x", label="Hack", type="html")


def test_category_names_are_trimmed_and_blank_names_rejected():
    assert CategoryInput(name="  Mini Sumo  ", description="  prueba  ").model_dump() == {
        "name": "Mini Sumo", "description": "prueba",
    }
    with pytest.raises(ValueError):
        CategoryInput(name="   ")


def test_category_roster_rejects_negative_and_inverted_bounds():
    with pytest.raises(ValueError):
        EventCategoryCreateInput(name="Mini", min_participants=0)
    with pytest.raises(ValueError):
        EventCategoryCreateInput(name="Mini", min_participants=3, max_participants=2)
    with pytest.raises(ValueError):
        EventCategoryCreateInput(name="Mini", min_coaches=2, max_coaches=1)


def test_tariff_rejects_negative_amount_and_inverted_validity():
    common = {"event_id": 1, "category_id": 1, "valid_from": "2027-04-02"}
    with pytest.raises(ValueError):
        TariffInput(**common, amount="-15")
    with pytest.raises(ValueError):
        TariffInput(**common, amount="15", valid_until="2027-04-01")


def test_team_and_robot_names_reject_whitespace_only():
    from app.schemas.resources import RobotInput, TeamInput

    with pytest.raises(ValueError):
        TeamInput(name="   ", institution_id=1)
    with pytest.raises(ValueError):
        RobotInput(name="   ")
