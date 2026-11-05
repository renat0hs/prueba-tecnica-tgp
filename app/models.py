from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'procesado', 'error')",
            name="leads_estado_valido",
        ),
        Index("idx_leads_estado", "estado"),
    )

    # Mapped[str] -> NOT NULL; Mapped[str | None] -> acepta NULL
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_empresa: Mapped[str] = mapped_column(Text)
    dominio: Mapped[str] = mapped_column(Text)
    cargo_contacto: Mapped[str] = mapped_column(Text)

    # server_default: el valor por defecto lo pone Postgres, no Python
    estado: Mapped[str] = mapped_column(Text, server_default="pendiente")
    correo_asunto: Mapped[str | None] = mapped_column(Text)
    correo_cuerpo: Mapped[str | None] = mapped_column(Text)
    error_motivo: Mapped[str | None] = mapped_column(Text)
    intentos: Mapped[int] = mapped_column(server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
