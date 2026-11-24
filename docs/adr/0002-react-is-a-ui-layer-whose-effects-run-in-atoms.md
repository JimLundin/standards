# React is a UI layer whose effects run in atoms

TypeScript gains a third layer, `ui`, for React packages: it imports the core and the contracts in it, never the shell, and every effect it runs is an `@effect/atom-react` atom over a browser layer, so components hold no `useEffect`, Promise or browser global. Components are held to the shell's decision counts, so their logic moves into core view models, where property and mutation tests reach it.

## Options rejected

- Leaving UI out of the standard: every project that follows it ships a React frontend, so that would exempt most of its TypeScript.
- Treating UI as shell: the shell's runtime is Node's, and the UI's state and effects need React's lifecycle, which atoms bridge.
