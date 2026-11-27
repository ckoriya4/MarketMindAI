
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { apiUrl } from "./config/api";
import "./AuthGate.css";

type User = {
    id: number;
    full_name: string;
    email: string;
    phone: string;
    email_verified: boolean;
    phone_verified: boolean;
};

type AuthResponse = {
    access_token: string;
    token_type?: string;
    user: User;
};

const TOKEN_KEY = "marketmind_access_token";

async function api(path: string, body?: unknown, token?: string) {
    const response = await fetch(apiUrl(path), {
        method: body !== undefined ? "POST" : "GET",
        headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        ...(body !== undefined
            ? { body: JSON.stringify(body) }
            : {}),
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        let errorMessage = `Request failed (${response.status})`;

        if (Array.isArray(data.detail)) {
            errorMessage = data.detail
                .map((item: {
                    loc?: unknown[];
                    msg?: string;
                    type?: string;
                }) => {
                    const field = Array.isArray(item.loc)
                        ? item.loc.filter(Boolean).join(" → ")
                        : "Field";

                    return `${field}: ${item.msg || "Invalid value"}`;
                })
                .join("\n");
        } else if (typeof data.detail === "string") {
            errorMessage = data.detail;
        }

        throw new Error(errorMessage);
    }

    return data;
}

export default function AuthGate({
    children,
}: {
    children: React.ReactNode;
}) {
    const [mode, setMode] = useState<"login" | "register" | "verify">("login");

    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [phone, setPhone] = useState("+91");
    const [password, setPassword] = useState("");

    const [otp, setOtp] = useState("");

    const [token, setToken] = useState(
        () => localStorage.getItem(TOKEN_KEY) || ""
    );

    const [user, setUser] = useState<User | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");

    // =====================================================
    // CHECK EXISTING SESSION
    // =====================================================

    useEffect(() => {
        if (!token) {
            setUser(null);
            return;
        }

        let cancelled = false;

        api("/api/auth/me", undefined, token)
            .then((data) => {
                if (!cancelled) {
                    setUser(data.user);
                }
            })
            .catch(() => {
                if (!cancelled) {
                    localStorage.removeItem(TOKEN_KEY);
                    setToken("");
                    setUser(null);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [token]);

    // =====================================================
    // SAVE LOGIN SESSION
    // =====================================================

    const saveSession = (data: AuthResponse) => {
        localStorage.setItem(TOKEN_KEY, data.access_token);
        setToken(data.access_token);
        setUser(data.user);
    };

    // =====================================================
    // FORM SUBMIT
    // =====================================================

    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();

        setBusy(true);
        setError("");
        setMessage("");

        try {

            // =============================================
            // REGISTER
            // =============================================

            if (mode === "register") {

                const cleanName = name.trim();
                const cleanEmail = email.trim().toLowerCase();
                const cleanPhone = phone.trim().replace(/[\s-]/g, "");

                if (cleanName.length < 2) {
                    throw new Error("Please enter your full name.");
                }

                if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
                    throw new Error("Please enter a valid email address.");
                }

                if (!/^\+[1-9]\d{7,14}$/.test(cleanPhone)) {
                    throw new Error(
                        "Enter a valid international phone number. Example: +919876543210"
                    );
                }

                if (password.length < 10) {
                    throw new Error(
                        "Password must contain at least 10 characters."
                    );
                }

                // Only email verification is supported.
                await api("/api/auth/register", {
                    full_name: cleanName,
                    email: cleanEmail,
                    phone: cleanPhone,
                    password,
                });

                setEmail(cleanEmail);
                setPhone(cleanPhone);
                setOtp("");
                setMode("verify");

                setMessage(
                    "Verification code sent to your email address."
                );
            }

            // =============================================
            // VERIFY EMAIL OTP
            // =============================================

            else if (mode === "verify") {

                if (!/^\d{6}$/.test(otp)) {
                    throw new Error(
                        "Enter a valid 6-digit verification code."
                    );
                }

                const data = await api("/api/auth/verify", {
                    email: email.trim().toLowerCase(),
                    otp,
                });

                saveSession(data);
            }

            // =============================================
            // LOGIN
            // =============================================

            else {

                const identifier = email.trim();

                if (!identifier) {
                    throw new Error("Enter your email or phone number.");
                }

                if (!password) {
                    throw new Error("Enter your password.");
                }

                const data = await api("/api/auth/login", {
                    identifier,
                    password,
                });

                saveSession(data);
            }

        } catch (e) {

            setError(
                e instanceof Error
                    ? e.message
                    : "Something went wrong. Please try again."
            );

        } finally {
            setBusy(false);
        }
    };

    // =====================================================
    // LOGOUT
    // =====================================================

    const logout = async () => {
        try {
            await api("/api/auth/logout", {}, token);
        } catch {
            // Local logout still proceeds.
        }

        localStorage.removeItem(TOKEN_KEY);

        setToken("");
        setUser(null);
        setPassword("");
        setMode("login");
        setError("");
        setMessage("");
    };

    // =====================================================
    // CHANGE LOGIN / REGISTER MODE
    // =====================================================

    const changeMode = (nextMode: "login" | "register") => {
        setMode(nextMode);
        setError("");
        setMessage("");
        setPassword("");
        setOtp("");
    };

    // =====================================================
    // AUTHENTICATED USER
    // =====================================================

    if (token && user) {
        return (
            <>
                {children}

                <button
                    className="mm-logout"
                    onClick={logout}
                    type="button"
                >
                    Logout · {user.full_name}
                </button>
            </>
        );
    }

    if (token && !user) {
        return (
            <div className="mm-auth-loading">
                Checking your session…
            </div>
        );
    }

    // =====================================================
    // AUTHENTICATION SCREEN
    // =====================================================

    return (
        <div className="mm-auth-shell">

            <form
                className="mm-auth-card"
                onSubmit={submit}
            >

                <div className="mm-auth-brand">
                    ◈ MarketMind AI
                </div>

                <h1>
                    {mode === "register"
                        ? "Create your account"
                        : mode === "verify"
                            ? "Verify your email"
                            : "Welcome back"}
                </h1>

                <p className="mm-auth-sub">
                    Secure access to your MarketMind AI dashboard
                </p>

                {/* =======================================
                    REGISTRATION FIELDS
                ======================================= */}

                {mode === "register" && (
                    <>

                        <label>
                            Full name

                            <input
                                type="text"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                required
                                minLength={2}
                                maxLength={100}
                                autoComplete="name"
                                placeholder="Enter your full name"
                            />
                        </label>

                        <label>
                            Email address

                            <input
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                autoComplete="email"
                                placeholder="example@gmail.com"
                            />
                        </label>

                        <label>
                            Phone number

                            <input
                                type="tel"
                                value={phone}
                                onChange={(e) => setPhone(e.target.value)}
                                required
                                autoComplete="tel"
                                placeholder="+919876543210"
                            />

                            <small>
                                Include country code. Example: +919876543210
                            </small>
                        </label>

                        <label>
                            Password

                            <input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                minLength={10}
                                maxLength={128}
                                autoComplete="new-password"
                                placeholder="Minimum 10 characters"
                            />
                        </label>

                        <p className="mm-auth-sub">
                            <strong>Email verification required.</strong>
                            <br />
                            A 6-digit OTP will be sent to your email.
                        </p>

                    </>
                )}

                {/* =======================================
                    LOGIN FIELDS
                ======================================= */}

                {mode === "login" && (
                    <>

                        <label>
                            Email or phone number

                            <input
                                type="text"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                autoComplete="username"
                                placeholder="Email or +919876543210"
                            />
                        </label>

                        <label>
                            Password

                            <input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                autoComplete="current-password"
                                placeholder="Enter your password"
                            />
                        </label>

                    </>
                )}

                {/* =======================================
                    EMAIL OTP VERIFICATION
                ======================================= */}

                {mode === "verify" && (
                    <>

                        <p className="mm-auth-sub">
                            A verification code has been sent to your email.
                        </p>

                        <label>
                            Registered email

                            <input
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                autoComplete="email"
                            />
                        </label>

                        <label>
                            6-digit email verification code

                            <input
                                type="text"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                value={otp}
                                onChange={(e) =>
                                    setOtp(
                                        e.target.value
                                            .replace(/\D/g, "")
                                            .slice(0, 6)
                                    )
                                }
                                required
                                pattern="[0-9]{6}"
                                maxLength={6}
                                placeholder="Enter 6-digit OTP"
                            />
                        </label>

                        <p className="mm-auth-sub">
                            The verification code expires after 10 minutes.
                        </p>

                    </>
                )}

                {/* =======================================
                    ERROR MESSAGE
                ======================================= */}

                {error && (
                    <div className="mm-auth-error">
                        {error}
                    </div>
                )}

                {/* =======================================
                    SUCCESS MESSAGE
                ======================================= */}

                {message && (
                    <div className="mm-auth-message">
                        {message}
                    </div>
                )}

                {/* =======================================
                    SUBMIT BUTTON
                ======================================= */}

                <button
                    className="mm-auth-submit"
                    type="submit"
                    disabled={busy}
                >
                    {busy
                        ? "Please wait…"
                        : mode === "register"
                            ? "Register & send Email OTP"
                            : mode === "verify"
                                ? "Verify Email & continue"
                                : "Login"}
                </button>

                {/* =======================================
                    MODE SWITCH
                ======================================= */}

                {mode !== "verify" ? (

                    <button
                        type="button"
                        className="mm-auth-link"
                        onClick={() =>
                            changeMode(
                                mode === "login"
                                    ? "register"
                                    : "login"
                            )
                        }
                    >
                        {mode === "login"
                            ? "New user? Create an account"
                            : "Already registered? Login"}
                    </button>

                ) : (

                    <button
                        type="button"
                        className="mm-auth-link"
                        onClick={() => {
                            setMode("register");
                            setOtp("");
                            setError("");
                            setMessage("");
                        }}
                    >
                        Back to registration
                    </button>

                )}

            </form>
        </div>
    );
}
