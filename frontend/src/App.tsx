import { useEffect, useState } from "react";

import "./App.css";

export default function App() {
  const [backendUp, setBackendUp] = useState(false);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => setBackendUp(response.ok))
      .catch(() => setBackendUp(false));
  }, []);

  return (
    <main className="app">
      <img className="app__logo" src="/mistral.svg" alt="Mistral" />
      <h1 className="app__title">Full stack starter</h1>
      <p className="app__subtitle">
        You are seeing the frontend running on localhost:3000
      </p>
      <span className={`badge ${backendUp ? "badge--ok" : "badge--down"}`}>
        <span className="badge__dot" />
        Backend {backendUp ? "running" : "offline"}
      </span>
    </main>
  );
}
