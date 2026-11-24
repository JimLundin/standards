import { RegistryProvider } from "@effect/atom-react";
import { Welcome } from "./welcome.tsx";
import { createRoot } from "react-dom/client";

createRoot(document.body).render(
  <RegistryProvider>
    <Welcome />
  </RegistryProvider>,
);
