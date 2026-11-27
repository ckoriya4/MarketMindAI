from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Literal

class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=10, max_length=128)
    verify_via: Literal["email", "phone"]

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value):
        value = value.strip().replace(" ", "").replace("-", "")
        if not value.startswith("+") or not value[1:].isdigit():
            raise ValueError("Phone must be in international format, e.g. +919876543210")
        return value

class VerifyRegistrationRequest(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r"^\d{6}$")

class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

class ResendOtpRequest(BaseModel):
    email: EmailStr
