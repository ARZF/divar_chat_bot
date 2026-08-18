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
