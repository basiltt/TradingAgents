import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { TradingAgentsNeumorphismPreview } from "@/design-system/neumorphism";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TradingAgentsNeumorphismPreview />
  </StrictMode>,
);
