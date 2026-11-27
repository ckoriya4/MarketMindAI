
from pydantic import BaseModel, EmailStr, Field, field_validator


# =========================================================
# REGISTER REQUEST
# EMAIL VERIFICATION ONLY
# =========================================================

class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value):
        value = value.strip()

        if len(value) < 2:
            raise ValueError("Full name must contain at least 2 characters.")

        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).strip().lower()

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value):
        value = value.strip().replace(" ", "").replace("-", "")

        if not value.startswith("+") or not value[1:].isdigit():
            raise ValueError(
                "Phone must be in international format, "
                "e.g. +919876543210"
            )

        return value


# =========================================================
# VERIFY REGISTRATION REQUEST
# =========================================================

class VerifyRegistrationRequest(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r"^\d{6}$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).strip().lower()


# =========================================================
# LOGIN REQUEST
# =========================================================

class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value):
        return value.strip()


# =========================================================
# RESEND EMAIL OTP REQUEST
# =========================================================

class ResendOtpRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).strip().lower()
