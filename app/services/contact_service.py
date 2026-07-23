from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.contact import Contact, ContactGroup
from app.models.wecom_archive_group import WeComArchiveGroup
from app.models.wecomapi_room_member_cache import WeComApiRoomMemberCache
from app.utils.datetime_utils import now_tz


class ContactService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def observe(self, *, group_id: str, archive_user_id: str | None, wecomapi_user_id: str | None, display_name: str | None, tenant_id: str | None, source: str, membership_status: str = "observed") -> Contact:
        identifier = wecomapi_user_id or archive_user_id
        if not identifier:
            raise ValueError("联系人缺少有效 ID")
        conditions = []
        if wecomapi_user_id:
            conditions.append(Contact.wecomapi_user_id == wecomapi_user_id)
        if archive_user_id:
            conditions.append(Contact.archive_user_id == archive_user_id)
        contact = self.db.scalar(select(Contact).where(or_(*conditions)).limit(1))
        if contact is None:
            contact = Contact(
                tenant_id=tenant_id,
                display_name=(display_name or identifier)[:255],
                archive_user_id=archive_user_id,
                wecomapi_user_id=wecomapi_user_id,
                source=source,
                last_confirmed_at=now_tz(),
            )
            self.db.add(contact)
            self.db.flush()
        else:
            if display_name:
                contact.display_name = display_name[:255]
            contact.archive_user_id = archive_user_id or contact.archive_user_id
            contact.wecomapi_user_id = wecomapi_user_id or contact.wecomapi_user_id
            contact.is_active = True
            contact.last_confirmed_at = now_tz()
        membership = self.db.scalar(select(ContactGroup).where(ContactGroup.contact_id == contact.id, ContactGroup.group_id == group_id))
        if membership is None:
            membership = ContactGroup(contact_id=contact.id, group_id=group_id, membership_status=membership_status, source=source)
            self.db.add(membership)
        else:
            membership.membership_status = membership_status
            membership.source = source
            membership.last_seen_at = now_tz()
            membership.updated_at = now_tz()
        self.db.flush()
        return contact

    def list_group(self, archive_group_id: str) -> tuple[str, str, str | None, list[dict]]:
        group = self.db.scalar(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == archive_group_id))
        if not group:
            raise ValueError("确认群不存在")
        rows = self.db.execute(
            select(Contact, ContactGroup)
            .join(ContactGroup, ContactGroup.contact_id == Contact.id)
            .where(ContactGroup.group_id == archive_group_id, ContactGroup.membership_status != "left", Contact.is_active.is_(True))
            .order_by(Contact.display_name.asc())
        ).all()
        items = [
            {
                "id": contact.id,
                "tenant_id": contact.tenant_id,
                "display_name": contact.display_name,
                "role": contact.role,
                "archive_user_id": contact.archive_user_id,
                "wecomapi_user_id": contact.wecomapi_user_id,
                "source": contact.source,
                "is_active": contact.is_active,
                "membership_status": membership.membership_status,
                "membership_source": membership.source,
                "last_seen_at": membership.last_seen_at,
            }
            for contact, membership in rows
        ]
        full = any(item["membership_source"] == "platform" for item in items)
        return archive_group_id, "platform_full" if full else "callback_observed", None if full else "当前仅包含平台可见或已在群里发过消息的人员", items

    def sync_cached_members(self, archive_group_id: str) -> int:
        group = self.db.scalar(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == archive_group_id))
        if not group or not group.wecomapi_room_id:
            return 0
        members = list(self.db.scalars(select(WeComApiRoomMemberCache).where(WeComApiRoomMemberCache.room_id == group.wecomapi_room_id)).all())
        for member in members:
            self.observe(
                group_id=archive_group_id,
                archive_user_id=None,
                wecomapi_user_id=member.user_id,
                display_name=member.display_name,
                tenant_id=group.tenant_id,
                source=member.source,
            )
        return len(members)
