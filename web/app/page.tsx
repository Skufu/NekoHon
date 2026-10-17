"use client";

import { useEffect } from "react";
import Reader from "@/components/Reader";
import { useAsk } from "@/lib/store";

export default function Page() {
  useEffect(() => {
    useAsk.getState().hydrateStore();
  }, []);

  return <Reader />;
}
