
import { useEffect, useState } from "react";
import { apiUrl } from "./config/api";

type KiteState =
    | "checking"
    | "connected"
    | "login_required"
    | "setup_required"
    | "connection_unverified"
    | "backend_unavailable";

interface KiteStatusResponse {
    state?: string;
    connected?: boolean;
    websocket_connected?: boolean;
    message?: string;
}

export default function KiteLoginButton() {

    const [state, setState] = useState<KiteState>("checking");
    const [result, setResult] = useState("");

    useEffect(() => {

        const url = new URL(window.location.href);
        const loginResult = url.searchParams.get("kite_login");

        let retryDelay = 15000;

        if (loginResult) {

            if (loginResult === "success") {

                setResult(
                    "Zerodha authentication completed. Verifying backend session..."
                );

                // Give the backend a moment to finish saving
                // the token and starting the WebSocket.
                retryDelay = 2000;

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

            const currentController = controller;

            const timeout = setTimeout(() => {
                currentController.abort();
            }, 12000);

            try {

                const response = await fetch(
                    apiUrl("/api/auth/kite/status"),
                    {
                        method: "GET",
                        signal: currentController.signal,
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

                const data: KiteStatusResponse =
                    await response.json();

                if (!active) return;

                if (
                    data.state === "connected" &&
                    data.connected === true
                ) {

                    setState("connected");

                    setResult(
                        "Zerodha Kite session verified."
                    );

                } else if (
                    data.state === "setup_required"
                ) {

                    setState("setup_required");

                } else if (
                    data.state === "connection_unverified"
                ) {

                    setState("connection_unverified");

                } else if (
                    data.state === "login_required"
                ) {

                    setState("login_required");

                } else {

                    setState("connection_unverified");
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
                        retryDelay
                    );

                    retryDelay = 15000;
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
