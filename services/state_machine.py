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
        "human": ConversationState.HUMAN_SUPPORT,
    },

    ConversationState.PRICE_MENU: {
        "back": ConversationState.MAIN_MENU,
    },

    ConversationState.SERVICE_MENU: {
        "back": ConversationState.MAIN_MENU,
    },

    ConversationState.HUMAN_SUPPORT: {
        "exit": ConversationState.MAIN_MENU,
    },
}

def transition(
    current_state: ConversationState,
    event: str,
) -> ConversationState:
    return TRANSITIONS.get(current_state, {}).get(
        event,
        current_state,
    )