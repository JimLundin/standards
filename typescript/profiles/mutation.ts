import { configureGlobal } from "fast-check";

configureGlobal({ endOnFailure: true, numRuns: 10, seed: 42 });
