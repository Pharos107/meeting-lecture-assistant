"""Xóa token nghe lại và vé WebSocket đã hết hạn."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import MediaToken, WsTicket


def delete_expired_secrets(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.query(MediaToken).filter(MediaToken.expires_at <= now).delete(synchronize_session=False)
    db.query(WsTicket).filter(WsTicket.expires_at <= now).delete(synchronize_session=False)


def purge_expired_secrets(db: Session) -> None:
    delete_expired_secrets(db)
    db.commit()
