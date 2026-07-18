"""Import all models so Alembic autogenerate & Base.metadata see them."""
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.billing import CreditTransaction, Plan, StripeEvent, Subscription
from app.models.billing_profile import BillingProfile
from app.models.errorlog import ErrorLog
from app.models.notification import Notification, NotificationPreference
from app.models.oauth import OAuthAccount
from app.models.rbac import Permission, Role, role_permissions, user_roles
from app.models.recovery import RecoveryCode
from app.models.setting import AppSetting
from app.models.ticket import Ticket, TicketMessage
from app.models.user import User, UserSession

__all__ = [
    "Base",
    "User",
    "UserSession",
    "Role",
    "Permission",
    "role_permissions",
    "user_roles",
    "Plan",
    "Subscription",
    "CreditTransaction",
    "StripeEvent",
    "BillingProfile",
    "Ticket",
    "TicketMessage",
    "ErrorLog",
    "RecoveryCode",
    "AuditLog",
    "OAuthAccount",
    "AppSetting",
    "Notification",
    "NotificationPreference",
]
