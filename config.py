from typing import FrozenSet, Dict, List

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DIVAR_API_KEY: str
    DIVAR_ACCESS_TOKEN: str
    DIVAR_REFRESH_TOKEN: str
    DIVAR_WEBHOOK_SECRET: str
    DIVAR_IDENTIFICATION_KEY: str
    DIVAR_APP_SLUG: str
    DIVAR_CLIENT_SECRET: str
    DIVAR_REDIRECT_URI: str
    DATABASE_URL: str
    EXPERIMENTAL_CLIENT_ID: int | None = None

    CORS_ALLOWED_ORIGINS: List[str] = []

    # --- 🔐 Seller Authentication (section 2.8) ---
    JWT_SECRET_KEY: str                        # signing key for access JWTs — .env only, never logged
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_LIFETIME_MINUTES: int = 30
    REFRESH_TOKEN_LIFETIME_DAYS: int = 30
    OTP_LENGTH: int = 6
    OTP_LIFETIME_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    OTP_REQUEST_COOLDOWN_SECONDS: int = 120    # min interval between OTP requests for same phone
    OTP_HMAC_KEY: str                          # secret key for HMAC-SHA256 OTP hashing — .env only
    SMS_PROVIDER_API_KEY: str | None = None    # for the SMS provider (no provider chosen yet)
    SMS_PROVIDER_URL: str | None = None        # SMS API endpoint (no provider chosen yet)

    
    # --- 🚀 New Chatbot Configuration Constants ---
    SUGGESTION_MIN_SCORE: float = 45.0
    MAX_BULK_RESULTS: int = 10

    WELCOME_MESSAGE: str = "سلام! به پشتیبانی خوش آمدید. برای قیمت بنویسید «قیمت»، برای گارانتی «گارانتی»، برای پشتیبانی «پشتیبانی»."
    PRICE_NOT_FOUND_MESSAGE: str = "متأسفانه قیمت این محصول در سیستم ما یافت نشد."
    PRICE_PROMPT_MESSAGE: str = "لطفاً نام محصول را وارد کنید. مثال: قیمت لپتاپ"
    WARRANTY_MESSAGE: str = "محصولات ما دارای گارانتی ۱۲ ماهه هستند."
    SUPPORT_MESSAGE: str = "تیم پشتیبانی ما در ساعات کاری ۹ تا ۱۸ پاسخگوی شما هستند."
    FALLBACK_MESSAGE: str = "پیام شما دریافت شد. برای راهنمایی بیشتر با پشتیبانی تماس بگیرید."
    UNRESOLVED_CLIENT_MESSAGE: str = "متأسفانه امکان پاسخگویی از طریق این مکالمه وجود ندارد. لطفاً از طریق صفحه آگهی وارد چت شوید."
    GREETING_REPLY_MESSAGE: str = "بفرمایید! چطور می‌توانم کمک کنم؟"
    GREETING_TOKENS: FrozenSet[str] = frozenset([
        "سلام", "درود", "سلامت", "هلو", "hi", "hello", "hey"
    ])
    FILTERED_KEYWORDS: FrozenSet[str] = frozenset([
        # --- Polite Words & Greetings (تعارف و احوالپرسی) ---
        "لطفاً", "لطفا", "خواهش", "می‌کنم", "میکنم", "ببخشید", "عزیزم", "داداش", "رئیس", 
        "حاجی", "برادر", "بزرگوار", "دوست", "گرامی", "سلام", "درود", "خسته", "نباشید",
        
        # --- Thanks & Sign-offs (تشکر و خداحافظی) ---
        "ممنون", "مرسی", "سپاس", "تشکر", "متشکرم", "لطف", "کردید", "کردین", "فدات", "شم",

        # --- Verbs of Wanting/Inquiry (افعال خواستن و پرسش) ---
        "می‌خوام", "میخوام", "می‌خوای", "میخوای", "می‌خواد", "میخواد", 
        "می‌خوایم", "میخوایم", "می‌خواید", "میخواید", "می‌خوان", "میخوان",
        "میشه", "میشه‌", "می‌شه", "بگید", "بگین", "بفرمایید", "بفرمایین",

        # --- Question Words & Slang (کلمات پرسشی و عامیانه) ---
        "چنده", "چند", "چیه", "چطوریاست", "چطوریه", "کدومه", "کدوم", "چنده‌",

        # --- Availability & Existential Words (موجودی و داشتن) ---
        "دارید", "دارین", "داری", "دارن", "موجوده", "موجود", "هست", "نیست",

        # --- Pronouns & Fillers (ضمایر و کلمات اضافه) ---
        "این", "اون", "اینو", "اونو", "واسه", "برای", "توی", "داخل", "یک", "یه"
    ])
    
    # Note: Pydantic handles dictionaries flawlessly, but mutable types like dicts 
    # should be declared with their types clearly typed out.
    KEYWORD_MAP: Dict[FrozenSet[str], str] = {
        frozenset(["price", "قیمت"]): "PRICE",
        frozenset(["warranty", "گارانتی"]): "WARRANTY",
        frozenset(["support", "پشتیبانی"]): "SUPPORT",
    }

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
