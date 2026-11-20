
import { useEffect, useState } from "react";
import { apiUrl } from "./config/api";

type KiteState =
    | "checking"
    | "connected"
    | "login_required"
    | "setup_required"
    | "connection_unverified"
    | "backend_unavailable";

export default function KiteLoginButton() {

    const [state, setState] = useState<KiteState>("checking");
    const [result, setResult] = useState("");

    useEffect(() => {

        const url = new URL(window.location.href);
        const loginResult = url.searchParams.get("kite_login");

        if (loginResult) {

            if (loginResult === "success") {
                setResult(
                    "Zerodha authentication completed. Verifying backend session..."
                );
            } else {
                setResult(
                    `Login failed (${loginResult}). Please try again.`
                );
            }

            url.searchParams.delete("kite_login");

            window.history.replaceState(
                {},
                "",
                url.pathname + url.search + url.hash
            );
        }

        let active = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | undefined;

        const loadStatus = async () => {

            controller = new AbortController();

            const timeout = setTimeout(() => {
                controller?.abort();
            }, 12000);

            try {

                const response = await fetch(
                    apiUrl("/api/auth/kite/status"),
                    {
                        method: "GET",
                        signal: controller.signal,
                        cache: "no-store",
                        headers: {
                            Accept: "application/json"
                        }
                    }
                );

                if (!response.ok) {
                    throw new Error(
                        `Status request failed: ${response.status}`
                    );
                }

                const data = await response.json();

                if (!active) return;

                const nextState = data.state as KiteState;

                if (
                    nextState === "connected" &&
                    data.connected === true
                ) {
                    setState("connected");
                    setResult("Zerodha Kite session verified.");
                } else if (
                    nextState === "setup_required"
                ) {
                    setState("setup_required");
                } else if (
                    nextState === "connection_unverified"
                ) {
                    setState("connection_unverified");
                } else {
                    setState("login_required");
                }

            } catch (error) {

                if (active) {
                    setState("backend_unavailable");
                }

            } finally {

                clearTimeout(timeout);

                if (active) {
                    timer = setTimeout(
                        loadStatus,
                        15000
                    );
                }
            }
        };

        void loadStatus();

        return () => {

            active = false;

            if (timer) {
                clearTimeout(timer);
            }

            controller?.abort();
        };

    }, []);

    const labels: Record<KiteState, string> = {

        checking: "Checking Kite connection...",

        connected: "Kite session verified",

        login_required: "Kite login required",

        setup_required: "Configure Kite API credentials in Render",

        connection_unverified: "Kite connection could not be verified",

        backend_unavailable: "Backend unavailable"
    };

    const connected = state === "connected";

    const statusColor =
        connected
            ? "#22c55e"
            : state === "backend_unavailable"
                ? "#ef4444"
                : "#f59e0b";

    return (
        <span
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 9,
                flexWrap: "wrap",
                padding: 5,
                fontSize: 11
            }}
        >

            <a
                href={apiUrl("/api/auth/kite/login")}
                style={{
                    background: "#1261dc",
                    color: "#ffffff",
                    borderRadius: 5,
                    padding: "7px 12px",
                    textDecoration: "none",
                    fontWeight: 600,
                    whiteSpace: "nowrap"
                }}
            >
                {connected ? "Reconnect Kite" : "Login with Kite"}
            </a>

            <span
                role="status"
                aria-live="polite"
                style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    color: statusColor,
                    fontWeight: 600
                }}
            >
                <span
                    style={{
                        width: 7,
                        height: 7,
                        borderRadius: "50%",
                        background: statusColor,
                        display: "inline-block"
                    }}
                />

                {labels[state]}
            </span>

            {result && (
                <span
                    style={{
                        width: "100%",
                        color: "#94a3b8",
                        fontSize: 10
                    }}
                >
                    {result}
                </span>
            )}

        </span>
    );
}
