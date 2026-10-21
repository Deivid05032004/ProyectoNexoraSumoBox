from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RegulationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    effective_from: date | None = None
    effective_until: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if not self.model_fields_set:
            raise ValueError("Indique al menos un campo para actualizar.")
        if "title" in self.model_fields_set:
            if self.title is None or not self.title.strip():
                raise ValueError("El título no puede quedar vacío.")
            self.title = self.title.strip()
        if "effective_from" in self.model_fields_set and self.effective_from is None:
            raise ValueError("effective_from no puede ser nulo.")
        if (self.effective_from is not None and self.effective_until is not None
                and self.effective_until < self.effective_from):
            raise ValueError("effective_until no puede ser anterior a effective_from.")
        return self
