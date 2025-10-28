import uuid
from datetime import datetime

from fastapi_users_db_sqlalchemy import GUID
from python3_commons.db import Base
from python3_commons.db.models.common import BaseDBUUIDModel
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class ApiKey(BaseDBUUIDModel, Base):
    __tablename__ = 'api_keys'

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey('users.id', name='fk_api_key_user', ondelete='RESTRICT'),
        index=True,
    )
    partner_name: Mapped[str] = mapped_column(String, unique=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
