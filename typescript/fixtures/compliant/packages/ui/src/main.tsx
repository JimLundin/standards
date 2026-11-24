import { RegistryProvider, useAtomValue } from "@effect/atom-react";
import { AsyncResult } from "effect/reactivity";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { greeting } from "./greeting.ts";

const Greeting = (): ReactNode => {
	const result = useAtomValue(greeting);
	return <p>{AsyncResult.getOrElse(result, () => "")}</p>;
};

createRoot(document.body).render(
	<RegistryProvider>
		<Greeting />
	</RegistryProvider>,
);
