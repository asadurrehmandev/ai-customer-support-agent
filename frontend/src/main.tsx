import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@fontsource/atkinson-hyperlegible/latin-400.css";
import "@fontsource/atkinson-hyperlegible/latin-700.css";
import "@fontsource/atkinson-hyperlegible-mono/latin-400.css";
import "./index.css";
import App from "./App.tsx";

const stored = localStorage.getItem("keel.theme");
const theme =
  stored === "light" || stored === "dark"
    ? stored
    : window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
document.documentElement.dataset.theme = theme;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
