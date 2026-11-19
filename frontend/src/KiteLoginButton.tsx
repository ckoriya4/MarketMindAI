
import { useEffect, useState } from "react";
import { apiUrl } from "./config/api";

export default function KiteLoginButton() {
    const [state, setState] = useState("checking");
    const [result, setResult] = useState("");

    useEffect(() => {
        const url = new URL(window.location.href);
        const value = url.searchParams.get("kite_login");

        if (value) {
            setResult(
                value === "success"
                    ? "Kite token saved automatically."
                    : `Login not completed (${value}). Please retry.`
            );

            url.searchParams.delete("kite_login");
            window.history.replaceState({}, "", url);
        }

        let active = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | undefined;

        const load = async () => {
            controller = new AbortController();

            const timeout = setTimeout(
                () => controller?.abort(),
                12000
            );

            try {
                const r = await fetch(
                    apiUrl("/api/auth/kite/status"),
                    {
                        signal: controller.signal,
                        cache: "no-store"
                    }
                );

                if (!r.ok) throw Error();

                const d = await r.json();

                if (active) setState(d.state);
            } catch {
                if (active) setState("backend_unavailable");
            } finally {
                clearTimeout(timeout);

                if (active) {
                    timer = setTimeout(load, 15000);
                }
            }
        };

        void load();

        return () => {
            active = false;
            clearTimeout(timer);
            controller?.abort();
        };
    }, []);

    const labels: Record<string, string> = {
        checking: "Checking Kite login…",
        connected: "Kite session verified",
        login_required: "Kite login required",
        setup_required: "Set API key + secret once in backend/.env",
        connection_unverified: "Kite connection not verified",
        backend_unavailable: "Backend unavailable"
    };

    return (
        <span
            style={{
                display: "inline-flex",
                gap: 8,
                alignItems: "center",
                flexWrap: "wrap",
                padding: 5,
                fontSize: 11
            }}
        >
            <a
                href={apiUrl("/api/auth/kite/login")}
                style={{
                    background: "#1261dc",
                    color: "white",
                    borderRadius: 4,
                    padding: "6px 10px",
                    textDecoration: "none"
                }}
            >
                {state === "connected" ? "Reconnect Kite" : "Login with Kite"}
            </a>

            <span role="status">
                {labels[state] || "Check Kite login"}
                {result ? " · " + result : ""}
            </span>
        </span>
    );
}
