from enum import StrEnum


class ConversationState(StrEnum):
    START = "START"
    MAIN_MENU = "MAIN_MENU"
    PRICE_MENU = "PRICE_MENU"
    SERVICE_MENU = "SERVICE_MENU"
    HUMAN_SUPPORT = "HUMAN_SUPPORT"

TRANSITIONS = {
    ConversationState.START: {
        "menu": ConversationState.MAIN_MENU,
    },

    ConversationState.MAIN_MENU: {
        "price": ConversationState.PRICE_MENU,
        "service": ConversationState.SERVICE_MENU,
        # No persistent human-support mode this phase: the bot hands out a phone
        # number and stays in the menu. HUMAN_SUPPORT is left defined but unreachable.
        "human": ConversationState.MAIN_MENU,
        "menu": ConversationState.MAIN_MENU,
    },

    ConversationState.PRICE_MENU: {
        "back": ConversationState.MAIN_MENU,
        "price": ConversationState.PRICE_MENU,
        "service": ConversationState.SERVICE_MENU,
        "human": ConversationState.MAIN_MENU,
        "menu": ConversationState.MAIN_MENU,
    },

    ConversationState.SERVICE_MENU: {
        "back": ConversationState.MAIN_MENU,
        "price": ConversationState.PRICE_MENU,
        "service": ConversationState.SERVICE_MENU,
        "human": ConversationState.MAIN_MENU,
        "menu": ConversationState.MAIN_MENU,
    },

    ConversationState.HUMAN_SUPPORT: {
        "exit": ConversationState.MAIN_MENU,
    },
}

# Bridges the two vocabularies: config.KEYWORD_MAP yields uppercase intents,
# TRANSITIONS consumes lowercase events. This is the only place they meet.
INTENT_EVENTS = {
    "PRICE": "price",
    "SERVICE": "service",
    "SUPPORT": "human",
    "WARRANTY": "human",
    "MENU": "menu",
}

def transition(
    current_state: ConversationState,
    event: str,
) -> ConversationState:
    return TRANSITIONS.get(current_state, {}).get(
        event,
        current_state,
    )