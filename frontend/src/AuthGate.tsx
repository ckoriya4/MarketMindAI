import { FormEvent, useEffect, useState } from "react";
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

const TOKEN_KEY = "marketmind_access_token";

async function api(path: string, body?: unknown, token?: string) {
    const response = await fetch(apiUrl(path), {
        method: body ? "POST" : "GET",
        headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
    const [mode, setMode] = useState<"login" | "register" | "verify">("login");
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [phone, setPhone] = useState("+91");
    const [password, setPassword] = useState("");
    const [verifyVia, setVerifyVia] = useState<"email" | "phone">("email");
    const [otp, setOtp] = useState("");
    const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
    const [user, setUser] = useState<User | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");

    useEffect(() => {
        if (!token) return;
        api("/api/auth/me", undefined, token)
            .then(data => setUser(data.user))
            .catch(() => {
                localStorage.removeItem(TOKEN_KEY);
                setToken("");
            });
    }, [token]);

    const saveSession = (data: { access_token: string; user: User }) => {
        localStorage.setItem(TOKEN_KEY, data.access_token);
        setToken(data.access_token);
        setUser(data.user);
    };

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        setBusy(true); setError(""); setMessage("");
        try {
            if (mode === "register") {
                await api("/api/auth/register", {
                    full_name: name, email, phone, password, verify_via: verifyVia,
                });
                setMode("verify");
                setMessage(`Verification code sent by ${verifyVia}.`);
            } else if (mode === "verify") {
                const data = await api("/api/auth/verify", { email, otp });
                saveSession(data);
            } else {
                const data = await api("/api/auth/login", { identifier: email, password });
                saveSession(data);
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : "Something went wrong.");
        } finally {
            setBusy(false);
        }
    };

    const logout = async () => {
        try { await api("/api/auth/logout", {}, token); } catch { /* local logout still proceeds */ }
        localStorage.removeItem(TOKEN_KEY);
        setToken(""); setUser(null); setMode("login");
    };

    if (token && user) {
        return <>{children}<button className="mm-logout" onClick={logout}>Logout · {user.full_name}</button></>;
    }
    if (token && !user) return <div className="mm-auth-loading">Checking your session…</div>;

    return (
        <div className="mm-auth-shell">
            <form className="mm-auth-card" onSubmit={submit}>
                <div className="mm-auth-brand">◈ MarketMind AI</div>
                <h1>{mode === "register" ? "Create your account" : mode === "verify" ? "Verify your account" : "Welcome back"}</h1>
                <p className="mm-auth-sub">Secure access to your MarketMind AI dashboard</p>

                {mode === "register" && <>
                    <label>Full name<input value={name} onChange={e => setName(e.target.value)} required minLength={2} /></label>
                    <label>Email address<input type="email" value={email} onChange={e => setEmail(e.target.value)} required /></label>
                    <label>Phone number (international format)<input value={phone} onChange={e => setPhone(e.target.value)} required placeholder="+919876543210" /></label>
                    <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={10} /></label>
                    <label>Verify using
                        <select value={verifyVia} onChange={e => setVerifyVia(e.target.value as "email" | "phone")}>
                            <option value="email">Email OTP</option><option value="phone">Phone OTP (Twilio)</option>
                        </select>
                    </label>
                </>}

                {mode === "login" && <>
                    <label>Email or phone number<input value={email} onChange={e => setEmail(e.target.value)} required placeholder="Email or +919876543210" /></label>
                    <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} required /></label>
                </>}

                {mode === "verify" && <>
                    <label>Registered email<input type="email" value={email} onChange={e => setEmail(e.target.value)} required /></label>
                    <label>6-digit verification code<input inputMode="numeric" autoComplete="one-time-code" value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} required pattern="\d{6}" /></label>
                    <p className="mm-auth-sub">The code expires after 10 minutes.</p>
                </>}

                {error && <div className="mm-auth-error">{error}</div>}
                {message && <div className="mm-auth-message">{message}</div>}
                <button className="mm-auth-submit" disabled={busy}>{busy ? "Please wait…" : mode === "register" ? "Register & send OTP" : mode === "verify" ? "Verify & continue" : "Login"}</button>

                {mode !== "verify" ? (
                    <button type="button" className="mm-auth-link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); setMessage(""); }}>
                        {mode === "login" ? "New user? Create an account" : "Already registered? Login"}
                    </button>
                ) : (
                    <button type="button" className="mm-auth-link" onClick={() => { setMode("register"); setOtp(""); }}>
                        Back to registration
                    </button>
                )}
            </form>
        </div>
    );
}
