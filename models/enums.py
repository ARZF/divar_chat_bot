from enum import StrEnum


class ConversationState(StrEnum):
    START = "START"
    MAIN_MENU = "MAIN_MENU"
    PRICE_MENU = "PRICE_MENU"
    SERVICE_MENU = "SERVICE_MENU"
    HUMAN_SUPPORT = "HUMAN_SUPPORT"


class PostConversationState(StrEnum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"


class SubscriptionStatus(StrEnum):
    """§3.10.3 — the only subscription statuses; no others may be invented."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    PENDING = "PENDING"
