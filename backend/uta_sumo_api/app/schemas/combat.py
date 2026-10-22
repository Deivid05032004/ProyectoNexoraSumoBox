from typing import Literal

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, field_validator, model_validator


class CurrentCombatUpdate(BaseModel):
    # Clients may send back a snapshot to preserve the scoreboard UI contract.
    # Display-only names/teams/winner are ignored; SQL remains their source of truth.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    match_id: int | None = Field(default=None, gt=0)
    status: Literal["PROGRAMADO", "EN_VIVO", "PAUSADO", "FINALIZADO", "CANCELADO"] | None = Field(
        default=None, validation_alias=AliasChoices("status", "estado"))
    score_a: int | None = Field(default=None, ge=0, le=1_000_000,
                                validation_alias=AliasChoices("score_a", "puntaje_a",
                                                              AliasPath("robotA", "puntos")))
    score_b: int | None = Field(default=None, ge=0, le=1_000_000,
                                validation_alias=AliasChoices("score_b", "puntaje_b",
                                                              AliasPath("robotB", "puntos")))
    reason: str | None = Field(default=None, min_length=1, max_length=500,
                               validation_alias=AliasChoices("reason", "motivo"))
    details: str | None = Field(default=None, max_length=1000,
                                validation_alias=AliasChoices("details", "detalles"))

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        return {
            "Programado": "PROGRAMADO", "En combate": "EN_VIVO",
            "Pausado": "PAUSADO", "Finalizado": "FINALIZADO",
            "Cancelado": "CANCELADO",
        }.get(value, value)

    @model_validator(mode="after")
    def validate_update(self):
        has_score_a = "score_a" in self.model_fields_set
        has_score_b = "score_b" in self.model_fields_set
        if has_score_a != has_score_b:
            raise ValueError("Envíe ambos puntajes en la misma actualización.")
        if has_score_a and not self.reason:
            raise ValueError("Indique el motivo del ajuste del marcador.")
        if self.reason is not None:
            reason = self.reason.strip()
            if not reason:
                raise ValueError("El motivo no puede quedar vacío.")
            self.reason = reason
        has_details = "details" in self.model_fields_set
        if self.match_id is None and self.status is None and not has_score_a and not has_details:
            raise ValueError("Indique un combate, estado o marcador para actualizar.")
        return self
