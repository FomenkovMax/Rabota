import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "@fontsource/prata";   // кириллица и латиница, грузится только нужный набор символов
import "./styles/tokens.css";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
