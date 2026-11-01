"use client";

// Dev-only: Lapse patches the global clock for the whole document and weighs
// ~1.7 MB, so this branch is dead in `next build` and the import never reaches
// web/out. Module scope, not an effect, so the patch lands before any component
// asks for a frame.
if (process.env.NODE_ENV !== "production" && typeof window !== "undefined") {
  void import("@aiforui/lapse/panel").then(({ mountLapse }) => mountLapse());
}

export default function LapsePanel() {
  return null;
}
