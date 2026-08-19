# chatbot.py
"""Backward-compatible re-export shim.

The implementations now live in ``services/chatbot_engine.py``,
``services/chatbot_conversation.py``, ``services/post_conversation.py``, and
``services/oauth_refresh.py``. This module only re-exports them so existing
importers (``api/webhook.py``) keep working unchanged.

Note for tests: these are value re-exports, not live aliases. Patching a name
on *this* module does not affect the moved functions, which resolve their
globals against their own module — patch the owning module instead.
"""
from services.chatbot_conversation import (
    TOUCHPOINT_NAMES,
    _lookup_conversation,
    _resolve_new_conversation,
    _state_of,
    handle_bot_reply,
    parse_start_message,
)
from services.chatbot_engine import (
    _extract_product_name,
    _handle_price_intent,
    _is_pure_greeting,
    _match_intent,
    generate_chatbot_reply,
)
from services.oauth_refresh import _refresh_supplier_token
from services.post_conversation import (
    _load_post_message_history,
    _resolve_post_conversation,
    handle_post_bot_reply,
)
# Re-exported as a module object, not a value: patching an attribute on it
# mutates the one shared services.divar module, so it still reaches every caller.
import services.divar as divar_service
